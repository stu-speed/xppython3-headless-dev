import pytest
import XPPython3

from simless.libs.fake_xp import FakeXP


# ===========================================================================
# Helpers
# ===========================================================================

def register_plugin(name, iface_cls):
    import sys, types
    module = types.ModuleType(name)
    module.PythonInterface = iface_cls
    sys.modules[name] = module
    return name


def get_plugin_instance(xp: FakeXP):
    """
    Use FakeXP's public API to get plugin ID,
    then use loader.get_plugin(id) to retrieve the instance.
    Loader now assigns plugin IDs per-FakeXP instance, so ID=1 always.
    """
    plugin_id = XPPython3.xp.getMyID()   # PUBLIC API
    runner = xp._runner
    loader = runner.loader

    plugin = loader.get_plugin(plugin_id)
    assert plugin is not None, f"No plugin with id {plugin_id}"

    return plugin.instance


# ===========================================================================
# 1. Plugin reads unmanaged DataRefs directly
# ===========================================================================

def test_unmanaged_dataref_read_write():
    xp = FakeXP(debug=True, enable_gui=False, run_time=0.1)
    XPPython3.xp = xp

    class Plugin:
        def __init__(self):
            self.calls = []
            self.oat = None
            self.bus = None
            self.read_oat = None
            self.read_bus = None

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")

            self.oat = XPPython3.xp.findDataRef("sim/test/oat_unmanaged")
            self.bus = XPPython3.xp.findDataRef("sim/test/bus_array_unmanaged")

            XPPython3.xp.setDataf(self.oat, 12.5)
            XPPython3.xp.setDatavf(self.bus, [1.0, 2.0, 3.0], 0, 3)

            self.read_oat = XPPython3.xp.getDataf(self.oat)
            size = XPPython3.xp.getDatavf(self.bus, None, 0, 0)
            out = [0.0] * size
            XPPython3.xp.getDatavf(self.bus, out, 0, size)
            self.read_bus = out[:3]

            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    mod = register_plugin("unmanaged_rw_plugin", Plugin)
    xp._run_plugin_lifecycle([mod])

    plugin = get_plugin_instance(xp)

    assert plugin.calls == ["start", "enable", "disable", "stop"]
    assert plugin.read_oat == 12.5
    assert plugin.read_bus == [1.0, 2.0, 3.0]


# ===========================================================================
# 2. Unmanaged DataRefs used inside UI callbacks
# ===========================================================================

def test_unmanaged_dataref_ui_updates():
    xp = FakeXP(debug=True, enable_gui=False, run_time=0.1)
    XPPython3.xp = xp

    class Plugin:
        def __init__(self):
            self.calls = []
            self.oat = None
            self.slider = None
            self.last_written = None

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")

            self.oat = XPPython3.xp.findDataRef("sim/test/oat_gui")

            self.slider = XPPython3.xp.createWidget(
                100, 200, 200, 100,
                1, "", 0, 0,
                XPPython3.xp.WidgetClass_ScrollBar,
            )
            XPPython3.xp.setWidgetProperty(
                self.slider,
                XPPython3.xp.Property_ScrollBarType,
                XPPython3.xp.ScrollBarTypeSlider,
            )
            XPPython3.xp.setWidgetProperty(
                self.slider,
                XPPython3.xp.Property_ScrollBarSliderPosition,
                15,
            )

            XPPython3.xp.setDataf(self.oat, float(15))
            self.last_written = XPPython3.xp.getDataf(self.oat)

            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    mod = register_plugin("unmanaged_ui_plugin", Plugin)
    xp._run_plugin_lifecycle([mod])

    plugin = get_plugin_instance(xp)

    assert plugin.calls == ["start", "enable", "disable", "stop"]
    assert plugin.last_written == 15.0


# ===========================================================================
# 3. Unmanaged DataRefs read inside flightloop
# ===========================================================================

def test_unmanaged_dataref_flightloop_read():
    xp = FakeXP(debug=True, enable_gui=False, run_time=0.2)
    XPPython3.xp = xp

    class Plugin:
        def __init__(self):
            self.calls = []
            self.oat = None
            self.last_read = None

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")

            self.oat = XPPython3.xp.findDataRef("sim/test/oat_loop")
            XPPython3.xp.setDataf(self.oat, 33.3)

            def fl_cb(since, elapsed, counter, refcon=None):
                self.last_read = XPPython3.xp.getDataf(self.oat)
                return 0.1

            self.floop = XPPython3.xp.createFlightLoop(fl_cb)
            XPPython3.xp.scheduleFlightLoop(self.floop, -1)

            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    mod = register_plugin("unmanaged_loop_plugin", Plugin)
    xp._run_plugin_lifecycle([mod])

    plugin = get_plugin_instance(xp)

    assert plugin.calls == ["start", "enable", "disable", "stop"]
    assert plugin.last_read == 33.3


# ===========================================================================
# 4. Unmanaged DataRefs: array write via UI
# ===========================================================================

def test_unmanaged_array_write_via_ui():
    xp = FakeXP(debug=True, enable_gui=False, run_time=0.1)
    XPPython3.xp = xp

    class Plugin:
        def __init__(self):
            self.calls = []
            self.bus = None
            self.slider = None
            self.last_bus = None

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")

            self.bus = XPPython3.xp.findDataRef("sim/test/bus_array")

            XPPython3.xp.setDatavf(self.bus, [9.0], 1, 1)

            size = XPPython3.xp.getDatavf(self.bus, None, 0, 0)
            out = [0.0] * size
            XPPython3.xp.getDatavf(self.bus, out, 0, size)
            self.last_bus = out

            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    mod = register_plugin("unmanaged_array_plugin", Plugin)
    xp._run_plugin_lifecycle([mod])

    plugin = get_plugin_instance(xp)

    assert plugin.calls == ["start", "enable", "disable", "stop"]
    assert plugin.last_bus[1] == 9.0
