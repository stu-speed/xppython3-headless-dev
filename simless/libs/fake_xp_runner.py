# simless/libs/fake_xp_runner.py
# ===========================================================================
# FakeXPRunner
# Standalone simulation engine for FakeXP.
# ===========================================================================

from __future__ import annotations

import importlib
import time
from typing import Any, Optional, TYPE_CHECKING

import dearpygui.dearpygui as dpg
import XPPython3

from plugins.extensions.datarefs import DataRefManager, DataRefRegistry, DataRefSpec
from plugins.extensions.xp_interface import XPInterface

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPRunner:
    """
    Orchestrates a simless XPPython3 session using a FakeXP backend.
    """

    def __init__(
        self,
        xp: XPInterface,
        *,
        enable_gui: bool = True,
        run_time: float = -1.0,
    ) -> None:
        self.xp: XPInterface = xp
        setattr(self.xp, "_runner", self)

        self.enable_gui: bool = enable_gui
        self.run_time: float = run_time

    # ----------------------------------------------------------------------
    # DataRefManager binding
    # ----------------------------------------------------------------------
    def bind_dataref_manager(self, manager: DataRefManager) -> None:
        setattr(self.xp, "_dataref_manager", manager)
        if hasattr(self.xp, "_dbg"):
            self.xp._dbg("[Runner] DataRefManager bound")  # type: ignore

    # ----------------------------------------------------------------------
    # Plugin loading
    # ----------------------------------------------------------------------
    def load_plugin(self, module_path: str) -> None:
        xp = self.xp
        if hasattr(xp, "_dbg"):
            xp._dbg(f"[Runner] Loading plugin: {module_path}")  # type: ignore

        XPPython3.xp = xp

        mod = importlib.import_module(module_path)
        if not hasattr(mod, "PythonInterface"):
            raise RuntimeError(f"Module {module_path} has no PythonInterface class")

        plugin = mod.PythonInterface()

        registry: Optional[DataRefRegistry] = getattr(plugin, "registry", None)
        if isinstance(registry, DataRefRegistry):
            count = 0
            for accessor in registry._accessors.values():  # type: ignore
                spec: DataRefSpec = accessor._spec  # type: ignore
                self.register_dataref(spec.path, spec.default, bool(spec.writable))
                count += 1
            if hasattr(xp, "_dbg"):
                xp._dbg(f"[Runner] Auto-registered {count} datarefs")  # type: ignore

        plugins = getattr(xp, "_plugins", None)
        if plugins is None:
            plugins = []
            setattr(xp, "_plugins", plugins)
        plugins.append(plugin)

        if hasattr(xp, "_dbg"):
            xp._dbg(f"[Runner] Plugin loaded: {module_path}")  # type: ignore

    # ----------------------------------------------------------------------
    # DataRef registration
    # ----------------------------------------------------------------------
    def register_dataref(self, path: str, default: Any, writable: bool) -> None:
        xp = self.xp

        if isinstance(default, int):
            xp_type, is_array = 1, False
        elif isinstance(default, float):
            xp_type, is_array = 2, False
        elif isinstance(default, list):
            xp_type = 16 if all(isinstance(x, int) for x in default) else 8
            is_array = True
        elif isinstance(default, (bytes, bytearray)):
            xp_type, is_array = 32, True
        else:
            raise TypeError(f"Unsupported default type for dataref '{path}'")

        xp.registerDataRef(  # type: ignore
            path=path,
            xpType=xp_type,
            isArray=is_array,
            writable=writable,
            defaultValue=default,
        )

        if hasattr(xp, "_dbg"):
            xp._dbg(
                f"[Runner] Registered dataref: {path} "
                f"(default={default!r}, writable={writable}, xp_type={xp_type}, is_array={is_array})"
            )  # type: ignore

    # ----------------------------------------------------------------------
    # DearPyGui lifecycle
    # ----------------------------------------------------------------------
    def init_dpg(self) -> None:
        if hasattr(self.xp, "_dbg"):
            self.xp._dbg("[Runner] Initializing DearPyGui")  # type: ignore
        dpg.create_context()
        dpg.create_viewport(title="FakeXP", width=900, height=700)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    def shutdown_dpg(self) -> None:
        if hasattr(self.xp, "_dbg"):
            self.xp._dbg("[Runner] Shutting down DearPyGui")  # type: ignore
        dpg.destroy_context()

    # ----------------------------------------------------------------------
    # Flightloops
    # ----------------------------------------------------------------------
    def run_flightloops(self) -> None:
        xp = self.xp
        now = time.time()
        last = getattr(xp, "_last_frame_time", now)
        dt = now - last
        setattr(xp, "_last_frame_time", now)

        for cb in list(getattr(xp, "_flightloops", [])):
            try:
                cb(dt)
            except Exception as e:
                if hasattr(xp, "_dbg"):
                    xp._dbg(f"[Runner] Flightloop error: {e}")  # type: ignore

    def run_xppython_flightloops(self) -> None:
        xp = self.xp
        now = time.time()

        for entry in getattr(xp, "_flightloop_handles", []):
            if not entry.get("active", False):
                continue

            next_run = entry.get("next_run")
            if next_run is None or now < next_run:
                continue

            cb = entry.get("callback")
            try:
                returned_interval = cb(now, 0.0, 0, None)
            except Exception as e:
                if hasattr(xp, "_dbg"):
                    xp._dbg(f"[Runner] XPPython3 flightloop error: {e}")  # type: ignore
                returned_interval = 0

            if returned_interval > 0:
                entry["next_run"] = now + returned_interval
            elif returned_interval < 0:
                entry["next_run"] = now
            else:
                entry["active"] = False
                entry["next_run"] = None

    # ----------------------------------------------------------------------
    # One-frame simulation step
    # ----------------------------------------------------------------------
    def run_frame(self) -> bool:
        xp = self.xp

        self.run_flightloops()
        self.run_xppython_flightloops()

        if self.enable_gui:
            xp.graphics.run_draw_callbacks()          # type: ignore
            xp.widgets._draw_all_widgets()            # type: ignore
            dpg.render_dearpygui_frame()

            if not dpg.is_dearpygui_running():
                return False

        return True

    # ----------------------------------------------------------------------
    # Full plugin lifecycle
    # ----------------------------------------------------------------------
    def run_plugin_lifecycle(self) -> None:
        xp = self.xp
        plugins = getattr(xp, "_plugins", [])

        if not plugins:
            xp.log("[Runner] No plugins registered — nothing to run")
            return

        if self.enable_gui:
            self.init_dpg()

        # Start
        if hasattr(xp, "_dbg"):
            xp._dbg("[Runner] === XPluginStart phase ===")  # type: ignore
        for plugin in plugins:
            try:
                plugin.XPluginStart()
            except Exception as e:
                xp.log(f"[Runner] XPluginStart error: {e}")

        # Enable
        if hasattr(xp, "_dbg"):
            xp._dbg("[Runner] === XPluginEnable phase ===")  # type: ignore
        for plugin in plugins:
            try:
                plugin.XPluginEnable()
            except Exception as e:
                xp.log(f"[Runner] XPluginEnable error: {e}")

        # Main loop
        setattr(xp, "_running", True)
        start_time = time.time()
        target_dt = 1.0 / 60.0

        while getattr(xp, "_running", False):
            frame_start = time.time()

            if not self.run_frame():
                setattr(xp, "_running", False)
                break

            if self.run_time >= 0 and (time.time() - start_time) >= self.run_time:
                setattr(xp, "_running", False)
                break

            elapsed = time.time() - frame_start
            remaining = target_dt - elapsed
            if remaining > 0:
                time.sleep(remaining)

        # Disable
        for plugin in plugins:
            try:
                plugin.XPluginDisable()
            except Exception as e:
                xp.log(f"[Runner] XPluginDisable error: {e}")

        # Stop
        for plugin in plugins:
            try:
                plugin.XPluginStop()
            except Exception as e:
                xp.log(f"[Runner] XPluginStop error: {e}")

        if self.enable_gui:
            self.shutdown_dpg()

    # ----------------------------------------------------------------------
    # End loop
    # ----------------------------------------------------------------------
    def end_run_loop(self) -> None:
        setattr(self.xp, "_running", False)
