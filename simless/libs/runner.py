# ===========================================================================
# runner.py — deterministic simless execution harness
#
# ROLE
#   Provide deterministic, single‑source‑of‑truth execution for plugin code
#   outside of X‑Plane. The runner owns timing, callback scheduling, and
#   lifecycle sequencing. It must remain minimal, explicit, and free of
#   X‑Plane‑specific inference. All simulation behavior is delegated to
#   FakeXP and DataRefManager.
#
# CORE INVARIANTS
#   - Will use the Public API as much as possible
#   - Runner will use the Public API as much as possible
#   - Runner is the authoritative code for simless execution.
# ===========================================================================


from __future__ import annotations

import time
from typing import Any, Dict, List

from simless.libs.loader import SimlessPluginLoader, LoadedPlugin
from simless.libs.fake_xp_interface import FakeXPInterface


class SimlessRunner:
    def __init__(
        self,
        xp: FakeXPInterface,
        *,
        run_time: float = -1.0,
    ) -> None:
        self.xp = xp
        self.run_time = run_time
        self._running = False

        # Allow FakeXP to call back into us
        setattr(self.xp, "_runner", self)

        # ------------------------------------------------------------------
        # Plugin loader (authoritative registry)
        # ------------------------------------------------------------------
        self.loader: SimlessPluginLoader = SimlessPluginLoader(self.xp)

        # ------------------------------------------------------------------
        # Flightloop state (runner-owned)
        # ------------------------------------------------------------------
        self._next_flightloop_id: int = 1
        self._flightloops: Dict[int, Dict[str, Any]] = {}
        self._sim_time: float = 0.0  # single source of sim time

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
            fl["next_call"] = self._sim_time
        else:
            fl["next_call"] = self._sim_time + float(interval)

    def destroy_flightloop(self, loop_id: int) -> None:
        self._flightloops.pop(loop_id, None)

    # ----------------------------------------------------------------------
    # Stop loop (called by plugins via xp._quit() / xp.end_run_loop())
    # ----------------------------------------------------------------------
    def end_run_loop(self) -> None:
        """Stop the main loop immediately."""
        self._running = False
        self.xp.log("[Runner] end_run_loop() called — stopping main loop")

    # ----------------------------------------------------------------------
    # GUI lifecycle (graphics owns DearPyGui)
    # ----------------------------------------------------------------------
    def init_gui(self) -> None:
        self.xp.log("[Runner] GUI enabled (FakeXPGraphics manages DearPyGui)")

    def shutdown_gui(self) -> None:
        self.xp.log("[Runner] GUI shutdown requested (no-op for runner)")

    # ----------------------------------------------------------------------
    # Unified per-frame execution
    # ----------------------------------------------------------------------
    def run_one_frame(self) -> bool:
        xp = self.xp

        # 1. Advance sim time (60 Hz)
        dt = 1.0 / 60.0
        self._sim_time += dt
        xp._sim_time = self._sim_time
        sim_time = self._sim_time

        # 2. Flightloops
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

        # 3. Graphics frame
        try:
            if xp.enable_gui:
                xp._draw_frame()
        except Exception as exc:
            xp.log(f"[Runner] graphics/frame error: {exc!r}")
            return False

        return True

    # ----------------------------------------------------------------------
    # Lifecycle execution
    # ----------------------------------------------------------------------
    def run_plugin_lifecycle(self, plugin_names: list[str]) -> None:
        """
        Load plugins via loader, then run full lifecycle.
        """
        plugins = self.loader.load_plugins(plugin_names)
        self.run_lifecycle(plugins)

    def run_lifecycle(self, plugins: List[LoadedPlugin]) -> None:
        xp = self.xp

        if not plugins:
            xp.log("[Runner] No plugins to run")
            return

        if xp.debug:
            self.init_gui()

        # Enable
        xp.log("[Runner] === XPluginEnable BEGIN ===")
        disabled: set[int] = set()
        setattr(xp, "_disabled_plugins", disabled)

        for p in plugins:
            p.instance.xp = xp

            try:
                xp.log(f"[Runner] → XPluginEnable: {p.name}")
                result = p.instance.XPluginEnable()
            except Exception as exc:
                raise RuntimeError(f"[Runner] XPluginEnable failed for {p.name}: {exc!r}")

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

        if xp.enable_gui:
            self.shutdown_gui()
