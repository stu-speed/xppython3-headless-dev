# ===========================================================================
# fake_xp_runner.py — deterministic simless execution harness
#
# Responsibilities:
#   • Load plugins via FakeXPPluginLoader
#   • Inject xp.* namespace into plugin instances (XPPython3‑authentic)
#   • Execute lifecycle: Start → Enable → frame loop → Disable → Stop
#   • Maintain deterministic 60 Hz pacing
#   • Own ALL flightloop scheduling (FakeXP holds no scheduler state)
#   • Integrate DearPyGui when GUI mode is enabled
# ===========================================================================

import time
from typing import Any, Dict

import dearpygui.dearpygui as dpg

from .fake_xp_loader import FakeXPPluginLoader, LoadedPlugin


class FakeXPRunner:

    def __init__(
        self,
        xp: Any,
        *,
        enable_gui: bool = True,
        run_time: float = -1.0,
        debug: bool = False,
    ) -> None:
        self.xp = xp
        self.enable_gui = enable_gui
        self.run_time = run_time
        self.debug = debug
        self._running = False

        # Allow FakeXP to call back into us
        setattr(self.xp, "_runner", self)

        # ------------------------------------------------------------------
        # Flightloop state (runner-owned)
        # ------------------------------------------------------------------
        self._next_flightloop_id = 1
        self._flightloops: Dict[int, Dict[str, Any]] = {}
        self._sim_time = 0.0  # single source of sim time

    # ----------------------------------------------------------------------
    # Public API for FakeXP to forward scheduling calls
    # ----------------------------------------------------------------------
    def create_flightloop(self, version: int, params: Dict[str, Any]) -> int:
        """
        Modern X-Plane 12-style flightloop creation.
        'params' must contain: callback, refcon, phase, structSize.
        """
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
            # schedule immediately
            fl["next_call"] = self._sim_time
        else:
            fl["next_call"] = self._sim_time + float(interval)

    def destroy_flightloop(self, loop_id: int) -> None:
        self._flightloops.pop(loop_id, None)

    # ------------------------------------------------------------------
    # Stop loop (called by plugins via xp.end_run_loop())
    # ------------------------------------------------------------------
    def end_run_loop(self) -> None:
        """Stop the main loop immediately."""
        self._running = False
        self.xp.log("[Runner] end_run_loop() called — stopping main loop")

    # ------------------------------------------------------------------
    # GUI lifecycle
    # ------------------------------------------------------------------
    def init_gui(self) -> None:
        self.xp.log("[Runner] Initializing DearPyGui")
        dpg.create_context()
        dpg.create_viewport(title="FakeXP", width=900, height=700)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    def shutdown_gui(self) -> None:
        self.xp.log("[Runner] Shutting down DearPyGui")
        dpg.destroy_context()

    # ------------------------------------------------------------------
    # Unified per-frame execution
    # ------------------------------------------------------------------
    def run_one_frame(self) -> bool:
        xp = self.xp

        # 1. Advance sim time (60 Hz)
        dt = 1.0 / 60.0
        self._sim_time += dt
        sim_time = self._sim_time

        # 2. Flightloops (modern API)
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

                # If callback returns None or negative, keep previous interval
                if next_interval is None or next_interval < 0:
                    next_interval = fl["interval"]

                # X-Plane semantics: 0 means "do not reschedule"
                if next_interval == 0:
                    fl["next_call"] = float("inf")
                else:
                    fl["interval"] = float(next_interval)
                    fl["next_call"] = sim_time + float(next_interval)

        # 3. Draw callbacks
        try:
            xp.graphics.run_draw_callbacks()
        except Exception as exc:
            xp.log(f"[Runner] draw callback error: {exc!r}")

        # 4. GUI path
        if self.enable_gui:
            try:
                xp.widgets._draw_all_widgets()
                dpg.render_dearpygui_frame()

                if not dpg.is_dearpygui_running():
                    return False
            except Exception as exc:
                xp.log(f"[Runner] GUI frame error: {exc!r}")
                return False

        return True

    # ------------------------------------------------------------------
    # Lifecycle execution
    # ------------------------------------------------------------------
    def run_plugin_lifecycle(self, plugin_names: list[str]) -> None:
        loader = FakeXPPluginLoader(self.xp)
        plugins = loader.load_plugins(plugin_names)
        self.run_lifecycle(plugins)

    def run_lifecycle(self, plugins: list[LoadedPlugin]) -> None:
        xp = self.xp

        if not plugins:
            xp.log("[Runner] No plugins to run")
            return

        if self.enable_gui:
            self.init_gui()

        # Enable
        xp.log("[Runner] === XPluginEnable BEGIN ===")
        disabled = set()
        setattr(xp, "_disabled_plugins", disabled)

        for p in plugins:
            p.instance.xp = xp

            try:
                xp.log(f"[Runner] → XPluginEnable: {p.name}")
                result = p.instance.XPluginEnable()
            except Exception as exc:
                raise RuntimeError(f"[Runner] XPluginEnable failed for {p.name}: {exc!r}")

            # X-Plane semantics: 1 = enabled, 0 = disabled
            if not result:
                xp.log(f"[Runner] Plugin disabled by XPluginEnable: {p.name}")
                disabled.add(p.plugin_id)

        xp.log("[Runner] === XPluginEnable END ===")

        # Main loop
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

        # Disable
        xp.log("[Runner] === XPluginDisable BEGIN ===")
        for p in plugins:
            try:
                xp.log(f"[Runner] → XPluginDisable: {p.name}")
                p.instance.XPluginDisable()
            except Exception as exc:
                raise RuntimeError(f"[Runner] XPluginDisable failed for {p.name}: {exc!r}")
        xp.log("[Runner] === XPluginDisable END ===")

        # Stop
        xp.log("[Runner] === XPluginStop BEGIN ===")
        for p in plugins:
            try:
                xp.log(f"[Runner] → XPluginStop: {p.name}")
                p.instance.XPluginStop()
            except Exception as exc:
                raise RuntimeError(f"[Runner] XPluginStop failed for {p.name}: {exc!r}")
        xp.log("[Runner] === XPluginStop END ===")

        if self.enable_gui:
            self.shutdown_gui()
