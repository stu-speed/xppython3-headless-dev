# ===========================================================================
# FakeXPRunner
# Standalone simulation engine for FakeXP.
# Owns:
#   - Plugin loading
#   - DataRef registration
#   - Dummy promotion
#   - DataRefManager binding
#   - DearPyGui lifecycle
#   - 60 Hz main loop
#   - Full plugin lifecycle (Start, Enable, Loop, Disable, Stop)
# ===========================================================================

import time
import importlib
import dearpygui.dearpygui as dpg


class FakeXPRunner:
    def __init__(self, xp, *, enable_gui: bool = True, run_time: float = -1.0):
        self.xp = xp
        self.enable_gui = enable_gui
        self.run_time = run_time

    # ----------------------------------------------------------------------
    # DataRefManager binding
    # ----------------------------------------------------------------------
    def bind_dataref_manager(self, manager):
        self.xp._dataref_manager = manager
        self.xp._dbg("[Runner] DataRefManager bound")

    # ----------------------------------------------------------------------
    # Plugin loading
    # ----------------------------------------------------------------------
    def load_plugin(self, module_path: str) -> None:
        xp = self.xp
        xp._dbg(f"[Runner] Loading plugin: {module_path}")

        import XPPython3
        XPPython3.xp = xp

        mod = importlib.import_module(module_path)
        if not hasattr(mod, "PythonInterface"):
            raise RuntimeError(f"Module {module_path} has no PythonInterface class")

        plugin = mod.PythonInterface()

        # Auto-register DataRefRegistry specs
        if hasattr(plugin, "registry") and hasattr(plugin.registry, "_accessors"):
            for acc in plugin.registry._accessors.values():
                spec = acc._spec
                self.register_dataref(spec.path, spec.default, spec.writable)
            xp._dbg(f"[Runner] Auto-registered {len(plugin.registry._accessors)} datarefs")

        xp._plugins.append(plugin)
        xp._dbg(f"[Runner] Plugin loaded: {module_path}")

    # ----------------------------------------------------------------------
    # DataRef registration (owned by runner)
    # ----------------------------------------------------------------------
    def register_dataref(self, path: str, default, writable: bool):
        xp = self.xp

        # Determine type
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
            raise TypeError(f"Unsupported default type for {path}")

        # Allocate handle
        handle = xp._next_handle
        xp._next_handle += 1

        xp._handles[path] = handle
        xp._info[handle] = (xp_type, bool(writable), is_array, 0)
        xp._values[handle] = default

        xp._dbg(f"[Runner] Registered dataref: {path} (default={default}, writable={writable})")

    # ----------------------------------------------------------------------
    # DearPyGui lifecycle
    # ----------------------------------------------------------------------
    def init_dpg(self) -> None:
        self.xp._dbg("[Runner] Initializing DearPyGui")
        dpg.create_context()
        dpg.create_viewport(title="FakeXP", width=900, height=700)
        dpg.setup_dearpygui()
        dpg.show_viewport()

    def shutdown_dpg(self) -> None:
        self.xp._dbg("[Runner] Shutting down DearPyGui")
        dpg.destroy_context()

    # ----------------------------------------------------------------------
    # Flightloops
    # ----------------------------------------------------------------------
    def run_flightloops(self) -> None:
        xp = self.xp
        now = time.time()
        dt = now - xp._last_frame_time
        xp._last_frame_time = now

        for cb in list(xp._flightloops):
            try:
                cb(dt)
            except Exception as e:
                xp._dbg(f"[Runner] Flightloop error: {e}")

    def run_xppython_flightloops(self) -> None:
        xp = self.xp
        now = time.time()

        for entry in xp._flightloop_handles:
            if not entry["active"]:
                continue

            next_run = entry["next_run"]
            if next_run is None or now < next_run:
                continue

            cb = entry["callback"]
            try:
                returned_interval = cb(now, 0.0, 0, None)
            except Exception as e:
                xp._dbg(f"[Runner] XPPython3 flightloop error: {e}")
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
            xp.graphics.run_draw_callbacks()
            xp.widgets._draw_all_widgets()
            dpg.render_dearpygui_frame()

            if not dpg.is_dearpygui_running():
                return False

        return True

    # ----------------------------------------------------------------------
    # Full plugin lifecycle
    # ----------------------------------------------------------------------
    def run_plugin_lifecycle(self) -> None:
        xp = self.xp

        if not xp._plugins:
            xp.log("[Runner] No plugins registered — nothing to run")
            return

        if self.enable_gui:
            self.init_dpg()

        xp._dbg("[Runner] === XPluginStart phase ===")
        for plugin in xp._plugins:
            xp._dbg(f"[Runner] Starting plugin: {plugin}")
            try:
                plugin.XPluginStart()
            except Exception as e:
                xp.log(f"[Runner] XPluginStart error: {e}")
        xp._dbg("[Runner] XPluginStart complete")

        xp._dbg("[Runner] === XPluginEnable phase ===")
        for plugin in xp._plugins:
            xp._dbg(f"[Runner] Enabling plugin: {plugin}")
            try:
                plugin.XPluginEnable()
            except Exception as e:
                xp.log(f"[Runner] XPluginEnable error: {e}")
        xp._dbg("[Runner] XPluginEnable complete")

        xp._dbg("[Runner] === Entering main loop ===")
        xp._running = True

        target_dt = 1.0 / 60.0
        start_time = time.time()

        while xp._running:
            frame_start = time.time()

            if not self.run_frame():
                xp._dbg("[Runner] DearPyGui closed — exiting main loop")
                xp._running = False
                break

            if self.run_time >= 0:
                if (time.time() - start_time) >= self.run_time:
                    xp._dbg("[Runner] run_time reached — exiting main loop")
                    xp._running = False
                    break

            elapsed = time.time() - frame_start
            remaining = target_dt - elapsed
            if remaining > 0:
                time.sleep(remaining)

        xp._dbg("[Runner] Main loop complete")

        xp._dbg("[Runner] === XPluginDisable phase ===")
        for plugin in xp._plugins:
            xp._dbg(f"[Runner] Disabling plugin: {plugin}")
            try:
                plugin.XPluginDisable()
            except Exception as e:
                xp.log(f"[Runner] XPluginDisable error: {e}")
        xp._dbg("[Runner] XPluginDisable complete")

        xp._dbg("[Runner] === XPluginStop phase ===")
        for plugin in xp._plugins:
            xp._dbg(f"[Runner] Stopping plugin: {plugin}")
            try:
                plugin.XPluginStop()
            except Exception as e:
                xp.log(f"[Runner] XPluginStop error: {e}")
        xp._dbg("[Runner] XPluginStop complete")

        if self.enable_gui:
            self.shutdown_dpg()

    # ----------------------------------------------------------------------
    # End loop
    # ----------------------------------------------------------------------
    def end_run_loop(self) -> None:
        self.xp._dbg("[Runner] end_run_loop() called — stopping main loop")
        self.xp._running = False
