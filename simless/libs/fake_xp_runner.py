# ===========================================================================
# fake_xp_runner.py — deterministic simless execution harness
#
# Public API:
#     xp._run_plugin_lifecycle(["PI_ss_OTA", "dev_ota_gui"])
#
# Responsibilities:
#   • Internally load plugins using FakeXPPluginLoader
#   • Execute lifecycle: Enable → frame loop → Disable → Stop
#   • Maintain deterministic 60 Hz pacing
#   • Provide end_run_loop() so plugins can stop the loop
#   • Own ALL flightloop scheduling (FakeXP holds no scheduler state)
#   • Skip flightloops/draw callbacks for disabled plugins
# ===========================================================================

from __future__ import annotations

import time
from typing import Any, Callable

import dearpygui.dearpygui as dpg

from .fake_xp_loader import FakeXPPluginLoader, LoadedPlugin


class FakeXPRunner:
    """
    Executes plugin lifecycle:
        run_plugin_lifecycle(["PI_ss_OTA", "dev_ota_gui"])
    """

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
        # Legacy: list of {plugin_id, callback, interval}
        self._legacy_flightloops: list[dict] = []

        # Modern: list of {plugin_id, callback, interval, relative, next_call}
        self._modern_flightloops: list[dict] = []

    # ----------------------------------------------------------------------
    # Public API for FakeXP to forward scheduling calls
    # ----------------------------------------------------------------------

    def register_legacy_flightloop(self, plugin_id: int, callback: Callable, interval: float) -> None:
        self._legacy_flightloops.append({
            "plugin_id": plugin_id,
            "callback": callback,
            "interval": interval,
        })

    def create_modern_flightloop(self, plugin_id: int, params) -> dict:
        entry = {
            "plugin_id": plugin_id,
            "callback": params.callback,
            "interval": params.interval,
            "relative": params.relative,
            "next_call": 0.0,
        }
        self._modern_flightloops.append(entry)
        return entry

    def schedule_modern_flightloop(self, handle: dict, interval: float, relative: int) -> None:
        handle["interval"] = interval
        handle["relative"] = relative

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

        # 1. Advance sim time
        xp._sim_time += 1.0 / 60.0
        sim_time = xp._sim_time

        disabled = getattr(xp, "_disabled_plugins", set())

        # 2. Legacy flightloops
        for entry in self._legacy_flightloops:
            if entry["plugin_id"] in disabled:
                continue
            try:
                entry["callback"](sim_time)
            except Exception as exc:
                xp.log(f"[Runner] legacy flightloop error: {exc!r}")

        # 3. Modern flightloops
        for entry in self._modern_flightloops:
            if entry["plugin_id"] in disabled:
                continue

            if sim_time >= entry["next_call"]:
                try:
                    next_interval = entry["callback"](sim_time)
                except Exception as exc:
                    xp.log(f"[Runner] modern flightloop error: {exc!r}")
                    next_interval = entry["interval"]

                if next_interval is None or next_interval < 0:
                    next_interval = entry["interval"]

                entry["next_call"] = sim_time + next_interval

        # 4. Draw callbacks
        try:
            xp.graphics.run_draw_callbacks()
        except Exception as exc:
            xp.log(f"[Runner] draw callback error: {exc!r}")

        # 5. GUI path
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
                xp.log("[Runner] Main loop exit: GUI closed")
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
