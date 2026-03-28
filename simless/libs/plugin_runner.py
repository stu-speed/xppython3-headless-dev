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
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from simless.libs.dataref_viewer import FakeXPDataRefViewerClient
from simless.libs.fake_xp_types import XPShutdown
from simless.libs.plugin_loader import LoadedPlugin

if TYPE_CHECKING:
    import PythonPlugins.sshd_extensions.bridge_protocol as bridge_type
    from simless.libs.fake_xp import FakeXP


class SimlessRunner:
    """Deterministic simless execution harness.

    The runner provides a minimal, explicit, single‑source‑of‑truth
    execution environment for plugin code outside of X‑Plane. It owns
    timing, callback scheduling, lifecycle sequencing, and bridge
    synchronization. All simulation behavior is delegated to FakeXP and
    DataRefManager.
    """

    _bridge_client: bridge_type.XPBridgeClient | None
    _dataref_viewer: FakeXPDataRefViewerClient | None

    def __init__(
        self,
        fake_xp: FakeXP,
        enable_dataref_bridge: bool = False,
        bridge_host: Optional[str] = None,
        bridge_port: Optional[int] = None,
    ) -> None:
        # ------------------------------------------------------------------
        # Core state
        # ------------------------------------------------------------------
        self.fake_xp = fake_xp
        self._running: bool = False
        self._bridge_connected: bool = False
        self._bridge_last_error: str | None = None
        self._bridge_client = None
        self._dataref_viewer = None

        # ------------------------------------------------------------------
        # 1. Install synthetic XPPython3 runtime BEFORE importing plugin code
        # ------------------------------------------------------------------
        #
        # This ensures that:
        #   from XPPython3 import xp
        #   from XPPython3.xp import drawString
        #   import xp
        #
        # all resolve to the FakeXP façade, not plugins/XPPython3/xp.py.
        #
        from simless.libs.xppython3_runtime import wire_xppython3_runtime
        wire_xppython3_runtime(self.fake_xp)

        # ------------------------------------------------------------------
        # 2. Now it is safe to import bridge_protocol
        # ------------------------------------------------------------------
        #
        # bridge_protocol imports:
        #       from XPPython3 import xp
        #
        # If we imported it earlier, Python would load the real
        # plugins/XPPython3/xp.py and crash on:
        #       import XPLMCamera
        #
        import PythonPlugins.sshd_extensions.bridge_protocol as bridge_mod
        self._bridge_mod = bridge_mod

        # ------------------------------------------------------------------
        # 3. Create the dataref bridge (optional)
        # ------------------------------------------------------------------
        if enable_dataref_bridge:
            self._bridge_client = self._bridge_mod.XPBridgeClient(
                host=bridge_host or self._bridge_mod.BRIDGE_HOST,
                port=bridge_port or self._bridge_mod.BRIDGE_PORT,
            )
            self._attach_bridge_handle_callback()

        # ------------------------------------------------------------------
        # 4. Plugin loader (safe now that XPPython3 is synthetic)
        # ------------------------------------------------------------------
        from simless.libs.plugin_loader import SimlessPluginLoader
        self.loader: SimlessPluginLoader = SimlessPluginLoader(self.fake_xp)

        # ------------------------------------------------------------------
        # 5. Flightloop state
        # ------------------------------------------------------------------
        self._next_flightloop_id: int = 1
        self._flightloops: Dict[int, Dict[str, Any]] = {}
        self._sim_time: float = 0.0
        self._cycles: int = 0

    def get_bridge_status(self) -> tuple[bool, bool, str | None]:
        """
        Return bridge status as enabled, connected, last_error.
        """
        if self._bridge_client is None:
            return False, False, "Bridge not enabled"
        return True, self._bridge_client.is_connected, self._bridge_client.conn_status

    # ----------------------------------------------------------------------
    # Bridge registration callback wiring
    # ----------------------------------------------------------------------
    def _attach_bridge_handle_callback(self) -> None:
        """Attach a handle‑created callback so DataRefs auto‑register with the bridge.

        The DataRef subsystem emits discovery events; the runner decides
        whether and how those paths are synchronized externally.
        """
        self.fake_xp.attach_handle_callback(self._on_dataref_handle_created)

    def _on_dataref_handle_created(self, ref: Any) -> None:
        """Called synchronously when FakeXPDataRef creates a handle."""
        path = getattr(ref, "path", None)
        if not path:
            return
        if not self._bridge_connected:
            return

        try:
            self._bridge_client.add(path)
        except Exception as exc:
            try:
                self.fake_xp.log(f"[Runner] Bridge registration failed for {path}: {exc}")
            except Exception:
                pass

    def _register_all_datarefs_with_bridge(self) -> None:
        """Register all known DataRef paths with the bridge.

        Called once on initial bridge connection and again on reconnect.
        """
        if self._bridge_client is None:
            return
        all_handle_paths = self.fake_xp.all_handle_paths()

        try:
            self._bridge_client.add(all_handle_paths)
        except Exception:
            try:
                self.fake_xp.log(f"[Runner] Bridge registration failed for {all_handle_paths}")
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

        try:
            events: List[bridge_type.BridgeData] = self._bridge_client.poll_data()
        except ConnectionResetError as exc:
            self.fake_xp.log("[Runner] Bridge disconnected")
            self._bridge_connected = False
            self._bridge_last_error = f"connection reset: {exc}"
            return

        if not self._bridge_connected:
            self._bridge_connected = True
            self._bridge_last_error = None
            self._register_all_datarefs_with_bridge()

        for ev in events:
            if ev.type is self._bridge_mod.BridgeDataType.META:
                ref = self.fake_xp.get_handle(ev.path)
                assert ref is not None

                # Promote TYPE authority only
                self.fake_xp.promote_type(
                    ref=ref,
                    dtype=ev.dtype,
                    writable=bool(ev.writable),
                )

            elif ev.type is self._bridge_mod.BridgeDataType.UPDATE:
                ref = self.fake_xp.get_handle(ev.path)
                assert ref is not None, f"Unknown handle: {ev.path}"
                value = ev.value

                is_array = isinstance(value, (list, tuple, bytearray))
                size = len(value) if is_array else 1

                # Promote shape if needed (first time or shape change)
                if (
                    not ref.shape_known
                    or ref.is_array != is_array
                    or ref.size != size
                ):
                    self.fake_xp.promote_shape_from_value(
                        ref=ref,
                        value=value,
                    )
                else:
                    ref.value = value

            elif ev.type is self._bridge_mod.BridgeDataType.ERROR:
                self._bridge_last_error = ev.text
                self.fake_xp.log(f"[Bridge] ERROR: {ev.text}")

    # ----------------------------------------------------------------------
    # Stop loop
    # ----------------------------------------------------------------------
    def end_run_loop(self) -> None:
        self._running = False
        self.fake_xp.log("[Runner] end_run_loop() called — stopping main loop")

    # ----------------------------------------------------------------------
    # One frame
    # ----------------------------------------------------------------------
    def _run_one_frame(self) -> None:
        xp = self.fake_xp

        # 1. Advance sim time
        dt = 1.0 / 60.0
        self._sim_time += dt
        xp._sim_time = self._sim_time
        sim_time = self._sim_time

        # 2. Bridge sync
        if self._bridge_client is not None:
            self._manage_bridged_datarefs()

        # 3. Flightloops
        for fl in list(self._flightloops.values()):
            interval = fl["interval"]

            # XP semantics: interval == 0 → unscheduled, never runs
            if interval == 0:
                continue

            # Negative interval → N flightloops (runner decrements)
            if interval < 0:
                # Use counter-based scheduling
                if fl.get("_loops_remaining") is None:
                    fl["_loops_remaining"] = abs(int(interval))

                fl["_loops_remaining"] -= 1
                if fl["_loops_remaining"] > 0:
                    continue  # not time yet

                # Reset for next cycle
                fl["_loops_remaining"] = abs(int(interval))

                # Treat as "ready to run now"
                ready = True
            else:
                # Positive interval → time-based scheduling
                ready = (sim_time >= fl["next_call"])

            if not ready:
                continue

            # Compute callback args
            since = sim_time - fl["last_call"]
            elapsed = since
            counter = fl["counter"]
            refcon = fl["refcon"]

            try:
                next_interval = fl["callback"](since, elapsed, counter, refcon)
            except Exception as exc:
                xp.log(f"[Runner] modern flightloop error: {exc!r}")
                next_interval = fl["interval"]

            # Update timing
            fl["last_call"] = sim_time
            fl["counter"] += 1

            # XP semantics: None or <0 → reuse previous interval
            if next_interval is None or next_interval < 0:
                next_interval = fl["interval"]

            # interval == 0 → stop
            if next_interval == 0:
                fl["interval"] = 0
                fl["next_call"] = float("inf")
                continue

            # Store new interval
            fl["interval"] = float(next_interval)

            # Positive interval → schedule next call
            if next_interval > 0:
                fl["next_call"] = sim_time + float(next_interval)

        # 4. viewer
        if self._dataref_viewer:
            self._dataref_viewer.update()

        # 5. Graphics frame
        if xp.enable_gui:
            xp.draw_frame()

    # ----------------------------------------------------------------------
    # Full lifecycle (plugins = list of plugin names)
    # ----------------------------------------------------------------------
    def run_plugin_lifecycle(
        self,
        plugin_names: List[str],
        enable_dataref_viewer: bool = False,
        run_time: float = -1,
    ) -> None:
        xp = self.fake_xp

        if not plugin_names:
            xp.log("[Runner] No plugins to run")
            return

        # Optional FakeXP DataRef viewer (observer only)
        if enable_dataref_viewer:
            self._dataref_viewer = FakeXPDataRefViewerClient(xp)
            self._dataref_viewer.attach()

        # ------------------------------------------------------------
        # 1. Initialize graphics BEFORE plugin load/start/enable
        # ------------------------------------------------------------
        if xp.enable_gui:
            xp.init_graphics_root()
            xp.log("[Runner] GUI enabled (FakeXPGraphics manages DearPyGui)")

        # ------------------------------------------------------------
        # 2. XPluginStart (done by loader)
        # ------------------------------------------------------------
        plugins: List[LoadedPlugin] = self.loader.load_plugins(plugin_names)

        # ------------------------------------------------------------
        # 3. XPluginEnable
        # ------------------------------------------------------------
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

        # ------------------------------------------------------------
        # 4. Initialize XP widget → DPG window mapping
        # ------------------------------------------------------------
        if xp.enable_gui:
            xp.map_widgets_to_dpg()

        # ------------------------------------------------------------
        # 5. Main loop
        # ------------------------------------------------------------
        xp.log("[Runner] === Main loop BEGIN ===")
        self._running = True
        start = time.monotonic()
        target_dt = 1.0 / 60.0

        while self._running:
            frame_start = time.monotonic()

            try:
                self._run_one_frame()
            except XPShutdown:
                xp.log("[Runner] Main loop exit: shutdown")
                break
            except Exception as exc:
                xp.log(f"[Runner] graphics/frame error: {exc!r}")
                break

            if 0 <= run_time <= (time.time() - start):
                xp.log("[Runner] Main loop exit: run_time reached")
                break

            elapsed = time.monotonic() - frame_start
            remaining = target_dt - elapsed
            if remaining > 0:
                time.sleep(remaining)

        xp.log("[Runner] === Main loop END ===")

        # ------------------------------------------------------------
        # 6. XPluginDisable
        # ------------------------------------------------------------
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

        # ------------------------------------------------------------
        # 7. XPluginStop
        # ------------------------------------------------------------
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
        if self._dataref_viewer:
            self._dataref_viewer.detach()
            self._dataref_viewer = None

        if xp.enable_gui:
            xp.log("[Runner] === GUI Teardown ===")
