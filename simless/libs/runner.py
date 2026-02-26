# simless/libs/runner.py
# ===========================================================================
# SimlessRunner — production‑parity X‑Plane plugin lifecycle harness
#
# ROLE
#   Provide a deterministic, single‑source‑of‑truth execution environment
#   for XPPython3 plugins outside of X‑Plane. The runner owns lifecycle
#   sequencing, timing, flightloop scheduling, bridge synchronization, and
#   graphics frame dispatch. All simulation behavior is delegated to FakeXP
#   and DataRefManager.
#
# DESIGN
#   • Production‑parity ordering: graphics root is initialized BEFORE any
#     plugin load, start, or enable, matching X‑Plane’s widget subsystem.
#   • Plugins are fully independent: each receives a fresh xp interface and
#     may create windows or widgets during XPluginEnable without restriction.
#   • Runner drives a fixed‑rate simulation clock (60 Hz) and executes all
#     modern flightloops according to XPLM scheduling semantics.
#   • Bridge synchronization is runner‑owned: inbound META/UPDATE/ERROR
#     events are dispatched to DataRefManager before flightloops run.
#
# CORE INVARIANTS
#   • No inference, no hidden state: runner behavior is explicit and
#     deterministic across all environments.
#   • No plugin‑specific branching: lifecycle is identical for every plugin.
#   • Graphics, widgets, and DataRefManager are always initialized before
#     XPluginEnable, ensuring production‑authentic UI behavior.
#   • Flightloops, bridge sync, and graphics frames are executed in a strict,
#     documented order each frame.
#
# LIFECYCLE SEQUENCE
#   1. xp.init_graphics_root()        — graphics + widget system ready
#   2. loader.load_plugins()          — import plugin modules
#   3. xp._bind_datarefs()            — establish DataRefManager
#   4. XPluginStart()                 — plugin metadata only
#   5. XPluginEnable()                — plugins may create windows/UI
#   6. Main loop (flightloops → widgets → graphics)
#   7. XPluginDisable()
#   8. XPluginStop()
# ===========================================================================

from __future__ import annotations

import time
from typing import Any, Dict, List

from sshd_extensions.bridge_protocol import (
    BridgeDataType,
    BridgeData,
    XPBridgeClient,
    BRIDGE_HOST,
    BRIDGE_PORT,
)
from simless.libs.loader import SimlessPluginLoader, LoadedPlugin
from simless.libs.fake_xp_interface import FakeXPInterface


class SimlessRunner:
    """Deterministic simless execution harness.

    The runner provides a minimal, explicit, single‑source‑of‑truth
    execution environment for plugin code outside of X‑Plane. It owns
    timing, callback scheduling, lifecycle sequencing, and bridge
    synchronization. All simulation behavior is delegated to FakeXP and
    DataRefManager.
    """

    _bridge: XPBridgeClient | None

    def __init__(
        self,
        xp: FakeXPInterface,
        enable_dataref_bridge: bool = False,
        bridge_host: str = BRIDGE_HOST,
        bridge_port: int = BRIDGE_PORT,
    ) -> None:
        self.xp: FakeXPInterface = xp
        self._running: bool = False
        self._bridge_connected: bool = False
        self._bridge_last_error: str | None = None
        self._bridge = None

        # Allow FakeXP to call back into us
        setattr(self.xp, "simless_runner", self)

        # ------------------------------------------------------------------
        # Create the dataref bridge and manager helper
        # ------------------------------------------------------------------
        if enable_dataref_bridge:
            self._bridge = XPBridgeClient(
                self.xp,
                host=bridge_host,
                port=bridge_port,
            )
            self._attach_bridge_handle_callback()

        # Plugin loader
        self.loader: SimlessPluginLoader = SimlessPluginLoader(self.xp)

        # Flightloop state
        self._next_flightloop_id: int = 1
        self._flightloops: Dict[int, Dict[str, Any]] = {}
        self._sim_time: float = 0.0

    @property
    def bridge_status(self) -> tuple[bool, bool, str | None]:
        """
        Return bridge status as (enabled, connected, last_error).
        """
        return (
            self._bridge is not None,
            self._bridge_connected,
            self._bridge_last_error,
        )

    # ----------------------------------------------------------------------
    # Bridge registration callback wiring
    # ----------------------------------------------------------------------
    def _attach_bridge_handle_callback(self) -> None:
        """Attach a handle‑created callback so DataRefs auto‑register with the bridge.

        The DataRef subsystem emits discovery events; the runner decides
        whether and how those paths are synchronized externally.
        """
        self.xp.attach_handle_callback(self._on_dataref_handle_created)


    def _on_dataref_handle_created(self, ref: Any) -> None:
        """Called synchronously when FakeXPDataRef creates a handle."""
        path = getattr(ref, "path", None)
        if not path:
            return
        if not self._bridge_connected:
            return

        try:
            self._bridge.add(path)
        except Exception as exc:
            try:
                self.xp.log(f"[Runner] Bridge registration failed for {path}: {exc}")
            except Exception:
                pass

    def _register_all_datarefs_with_bridge(self) -> None:
        """Register all known DataRef paths with the bridge.

        Called once on initial bridge connection and again on reconnect.
        """
        if self._bridge is None:
            return
        all_handle_paths = self.xp.all_handle_paths()

        try:
            self._bridge.add(all_handle_paths)
        except Exception:
            try:
                self.xp.log(f"[Runner] Bridge registration failed for {all_handle_paths}")
            except Exception:
                pass

    # ----------------------------------------------------------------------
    # Bridge management
    # ----------------------------------------------------------------------
    # NOTE:
    # is_dummy means both type and value are provisional.
    # It flips to False only on the first provider‑originated UPDATE,
    # never on META.
    def _manage_bridged_datarefs(self) -> None:
        """Poll bridge events and update DataRefManager state.

        Connection management is handled entirely by XPBridgeClient.poll().
        This method only:
          • polls for inbound events,
          • applies META/UPDATE changes,
          • marks DataRefs dummy on disconnect,
          • logs bridge errors.
        """
        xp = self.xp

        try:
            events: List[BridgeData] = self._bridge.poll_data()
        except ConnectionResetError as exc:
            xp.log("[Runner] Bridge disconnected")
            self._bridge_connected = False
            self._bridge_last_error = f"connection reset: {exc}"
            return

        if not self._bridge_connected:
            self._bridge_connected = True
            self._bridge_last_error = None
            self._register_all_datarefs_with_bridge()

        for ev in events:
            if ev.type is BridgeDataType.META:
                ref = xp.get_handle(ev.path)
                assert ref is not None

                # Promote TYPE authority only
                xp.promote_type(
                    ref=ref,
                    dtype=ev.dtype,
                    writable=bool(ev.writable),
                )

            elif ev.type is BridgeDataType.UPDATE:
                ref = xp.get_handle(ev.path)
                assert ref is not None
                value = ev.value

                is_array = isinstance(value, (list, tuple, bytearray))
                size = len(value) if is_array else 1

                # Promote shape if needed (first time or shape change)
                if (
                    not ref.shape_known
                    or ref.is_array != is_array
                    or ref.size != size
                ):
                    xp.promote_shape_from_value(
                        ref=ref,
                        value=value,
                    )

                # Fast path: write value
                ref.value = value

            elif ev.type is BridgeDataType.ERROR:
                self._bridge_last_error = ev.text
                xp.log(f"[Bridge] ERROR: {ev.text}")

    # ----------------------------------------------------------------------
    # Flightloop API (runner‑owned)
    # ----------------------------------------------------------------------
    def create_flightloop(self, version: int, params: Dict[str, Any]) -> int:
        loop_id = self._next_flightloop_id
        self._next_flightloop_id += 1

        self._flightloops[loop_id] = {
            "callback": params["callback"],
            "refcon": params.get("refcon"),
            "phase": params.get("phase", 0),
            "structSize": params.get("structSize", 1),
            "interval": 0.0,
            "next_call": 0.0,
            "last_call": 0.0,
            "counter": 0,
        }
        return loop_id

    def schedule_flightloop(self, loop_id: int, interval: float) -> None:
        fl = self._flightloops.get(loop_id)
        if fl is None:
            return

        fl["interval"] = float(interval)
        fl["next_call"] = (
            self._sim_time if interval < 0 else self._sim_time + float(interval)
        )

    def destroy_flightloop(self, loop_id: int) -> None:
        self._flightloops.pop(loop_id, None)

    # ----------------------------------------------------------------------
    # Stop loop
    # ----------------------------------------------------------------------
    def end_run_loop(self) -> None:
        self._running = False
        self.xp.log("[Runner] end_run_loop() called — stopping main loop")

    # ----------------------------------------------------------------------
    # GUI lifecycle
    # ----------------------------------------------------------------------
    def init_gui(self) -> None:
        """Initialize GUI (FakeXPGraphics handles DearPyGui)."""
        self.xp.log("[Runner] GUI enabled (FakeXPGraphics manages DearPyGui)")

    def shutdown_gui(self) -> None:
        self.xp.log("[Runner] GUI shutdown requested (no‑op for runner)")

    # ----------------------------------------------------------------------
    # One frame
    # ----------------------------------------------------------------------
    def run_one_frame(self) -> bool:
        xp = self.xp

        # 1. Advance sim time
        dt = 1.0 / 60.0
        self._sim_time += dt
        xp._sim_time = self._sim_time
        sim_time = self._sim_time

        # 2. Bridge sync
        if self._bridge is not None:
            self._manage_bridged_datarefs()

        # 3. Flightloops
        for fl in list(self._flightloops.values()):
            if sim_time >= fl["next_call"]:
                since = sim_time - fl["last_call"]
                elapsed = since
                counter = fl["counter"]
                refcon = fl["refcon"]

                try:
                    next_interval = fl["callback"](since, elapsed, counter, refcon)
                except Exception as exc:
                    xp.log(f"[Runner] modern flightloop error: {exc!r}")
                    next_interval = fl["interval"]

                fl["last_call"] = sim_time
                fl["counter"] += 1

                if next_interval is None or next_interval < 0:
                    next_interval = fl["interval"]

                if next_interval == 0:
                    fl["next_call"] = float("inf")
                else:
                    fl["interval"] = float(next_interval)
                    fl["next_call"] = sim_time + float(next_interval)

        # 4. Graphics frame
        try:
            if xp.enable_gui:
                xp.draw_frame()
        except Exception as exc:
            xp.log(f"[Runner] graphics/frame error: {exc!r}")
            return False

        return True

    # ----------------------------------------------------------------------
    # Full lifecycle (plugins = list of plugin names)
    # ----------------------------------------------------------------------
    def run_plugin_lifecycle(
        self,
        plugin_names: List[str],
        enable_dataref_viewer: bool = False,
        run_time: float = -1,
    ) -> None:
        xp = self.xp

        if not plugin_names:
            xp.log("[Runner] No plugins to run")
            return

        # Optional FakeXP DataRef viewer (observer only)
        dataref_viewer = None
        if enable_dataref_viewer:
            from simless.libs.fake_xp_dataref_viewer import FakeXPDataRefViewerClient
            dataref_viewer = FakeXPDataRefViewerClient(xp)
            dataref_viewer.attach()

        # 1. Initialize graphics BEFORE plugin load/start/enable
        if xp.enable_gui:
            xp.init_graphics_root()
            self.init_gui()

        # 2. XPluginStart done by loader
        plugins: List[LoadedPlugin] = self.loader.load_plugins(plugin_names)

        # 3. XPluginEnable
        xp.log("[Runner] === XPluginEnable BEGIN ===")

        for p in plugins:
            try:
                result = p.instance.XPluginEnable()
                xp.log(f"[Runner] → XPluginEnable: {p.name} ret={result}")
            except Exception as exc:
                raise RuntimeError(
                    f"[Runner] XPluginEnable failed for {p.name}: {exc!r}"
                )

            p.enabled = bool(result)
            if not p.enabled:
                xp.log(f"[Runner] Plugin disabled by XPluginEnable: {p.name}")

        xp.log("[Runner] === XPluginEnable END ===")

        # 4. Main loop
        xp.log("[Runner] === Main loop BEGIN ===")
        self._running = True
        start = time.monotonic()
        target_dt = 1.0 / 60.0

        while self._running:
            frame_start = time.monotonic()

            if not self.run_one_frame():
                xp.log("[Runner] Main loop exit: GUI closed or fatal error")
                break

            # Viewer is value-only; no discovery here
            if dataref_viewer:
                dataref_viewer.poll()

            if 0 <= run_time <= (time.time() - start):
                xp.log("[Runner] Main loop exit: run_time reached")
                break

            elapsed = time.monotonic() - frame_start
            remaining = target_dt - elapsed
            if remaining > 0:
                time.sleep(remaining)

        xp.log("[Runner] === Main loop END ===")

        # 5. XPluginDisable
        xp.log("[Runner] === XPluginDisable BEGIN ===")
        for p in plugins:
            try:
                xp.log(f"[Runner] → XPluginDisable: {p.name}")
                p.instance.XPluginDisable()
                p.enabled = False
            except Exception as exc:
                raise RuntimeError(
                    f"[Runner] XPluginDisable failed for {p.name}: {exc!r}"
                )
        xp.log("[Runner] === XPluginDisable END ===")

        # 6. XPluginStop
        xp.log("[Runner] === XPluginStop BEGIN ===")
        for p in plugins:
            try:
                xp.log(f"[Runner] → XPluginStop: {p.name}")
                p.instance.XPluginStop()
            except Exception as exc:
                raise RuntimeError(
                    f"[Runner] XPluginStop failed for {p.name}: {exc!r}"
                )
        xp.log("[Runner] === XPluginStop END ===")

        # Tear down viewer
        if dataref_viewer:
            dataref_viewer.detach()
            dataref_viewer = None

        if xp.enable_gui:
            self.shutdown_gui()
