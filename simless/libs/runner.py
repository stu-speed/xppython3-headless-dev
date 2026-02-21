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

from sshd_extensions.bridge_protocol import BridgeDataType, BridgeData, XPBridgeClient
from sshd_extensions.datarefs import DataRefSpec
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

    def __init__(
        self,
        xp: FakeXPInterface,
        *,
        run_time: float = -1.0,
    ) -> None:
        self.xp: FakeXPInterface = xp
        self.run_time: float = run_time
        self._running: bool = False

        # Allow FakeXP to call back into us
        setattr(self.xp, "_runner", self)

        self.bridge = XPBridgeClient(xp)

        # Plugin loader
        self.loader: SimlessPluginLoader = SimlessPluginLoader(self.xp)

        # Flightloop state
        self._next_flightloop_id: int = 1
        self._flightloops: Dict[int, Dict[str, Any]] = {}
        self._sim_time: float = 0.0

    # ----------------------------------------------------------------------
    # Bridge management
    # ----------------------------------------------------------------------
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
        mgr = xp._dataref_manager

        if not xp.enable_dataref_bridge or mgr is None:
            return

        # --------------------------------------------------------------
        # 1. Poll inbound events (connect/reconnect handled in poll())
        # --------------------------------------------------------------
        try:
            events: List[BridgeData] = self.bridge.poll_data()
        except ConnectionResetError:
            xp.log("[Runner] Bridge disconnected")

            # Mark all DataRefs as dummy until reconnect
            for path in mgr.all_paths():
                spec = mgr.get_spec(path)
                if spec is None:
                    continue
                spec.is_dummy = True
                mgr.add_spec(path, spec)

            return

        # --------------------------------------------------------------
        # 2. Dispatch events
        # --------------------------------------------------------------
        for ev in events:
            if ev.type is BridgeDataType.META:
                spec = mgr.get_spec(ev.path) or DataRefSpec.dummy(ev.path, required=False, default=0.0)

                # Update metadata
                spec.type = ev.dtype
                spec.writable = bool(ev.writable)
                spec.is_dummy = False

                # Create a FakeDataRef handle and bind it
                ref = xp.findDataRef(ev.path)
                spec.handle = ref

                mgr.add_spec(ev.path, spec)
            elif ev.type is BridgeDataType.UPDATE:
                # Now safe because META created a handle
                mgr.set_value(ev.path, ev.value)
            elif ev.type is BridgeDataType.ERROR:
                xp.log(f"[Bridge] ERROR: {ev.text}")

    # ----------------------------------------------------------------------
    # Flightloop API (runner-owned)
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
        if interval < 0:
            fl["next_call"] = self._sim_time
        else:
            fl["next_call"] = self._sim_time + float(interval)

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
        self.xp.log("[Runner] GUI shutdown requested (no-op for runner)")

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
                xp._draw_frame()
        except Exception as exc:
            xp.log(f"[Runner] graphics/frame error: {exc!r}")
            return False

        return True

    # ----------------------------------------------------------------------
    # Full lifecycle (plugins = list of plugin names)
    # ----------------------------------------------------------------------
    def run_plugin_lifecycle(self, plugin_names: List[str]) -> None:
        xp = self.xp

        if not plugin_names:
            xp.log("[Runner] No plugins to run")
            return

        # 1. Initialize graphics BEFORE plugin load/start/enable
        #    (production parity: widget system ready before plugins run)
        if xp.enable_gui:
            xp.init_graphics_root()
            self.init_gui()

        # 2. Load plugin modules by name → LoadedPlugin[]
        plugins: List[LoadedPlugin] = self.loader.load_plugins(plugin_names)

        # 3. XPluginEnable
        xp.log("[Runner] === XPluginEnable BEGIN ===")
        disabled: set[int] = set()
        setattr(xp, "_disabled_plugins", disabled)

        for p in plugins:
            try:
                xp.log(f"[Runner] → XPluginEnable: {p.name}")
                result = p.instance.XPluginEnable()
            except Exception as exc:
                raise RuntimeError(f"[Runner] XPluginEnable failed for {p.name}: {exc!r}")

            if not result:
                xp.log(f"[Runner] Plugin disabled by XPluginEnable: {p.name}")
                disabled.add(p.plugin_id)

        xp.log("[Runner] === XPluginEnable END ===")

        # 4. Main loop
        xp.log("[Runner] === Main loop BEGIN ===")
        self._running = True
        start = time.time()
        target_dt = 1.0 / 60.0

        while self._running:
            frame_start = time.time()

            if not self.run_one_frame():
                xp.log("[Runner] Main loop exit: GUI closed or fatal error")
                break

            if 0 <= self.run_time <= (time.time() - start):
                xp.log("[Runner] Main loop exit: run_time reached")
                break

            elapsed = time.time() - frame_start
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
            except Exception as exc:
                raise RuntimeError(f"[Runner] XPluginDisable failed for {p.name}: {exc!r}")
        xp.log("[Runner] === XPluginDisable END ===")

        # 6. XPluginStop
        xp.log("[Runner] === XPluginStop BEGIN ===")
        for p in plugins:
            try:
                xp.log(f"[Runner] → XPluginStop: {p.name}")
                p.instance.XPluginStop()
            except Exception as exc:
                raise RuntimeError(f"[Runner] XPluginStop failed for {p.name}: {exc!r}")
        xp.log("[Runner] === XPluginStop END ===")

        if xp.enable_gui:
            self.shutdown_gui()
