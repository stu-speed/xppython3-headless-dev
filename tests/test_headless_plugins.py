import sys
import types
import XPPython3

from simless.libs.fake_xp import FakeXP
from simless.libs.runner import SimlessRunner


def register_inline_plugin(name: str, plugin_obj) -> str:
    """
    Registers an inline plugin module so SimlessRunner can load it.
    """
    module = types.ModuleType(name)

    class PythonInterface:
        def __init__(self):
            self.obj = plugin_obj

        def XPluginStart(self):
            return self.obj.XPluginStart()

        def XPluginEnable(self):
            return self.obj.XPluginEnable()

        def XPluginDisable(self):
            return self.obj.XPluginDisable()

        def XPluginStop(self):
            return self.obj.XPluginStop()

    module.PythonInterface = PythonInterface
    sys.modules[name] = module
    return name


# ===========================================================================
# 1. Basic headless plugin lifecycle
# ===========================================================================

def test_headless_plugin_lifecycle():
    xp = FakeXP(debug=True, enable_gui=False)
    runner = SimlessRunner(xp, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    class Plugin:
        def __init__(self):
            self.calls = []

        def XPluginStart(self):
            self.calls.append("start")
            return "Test", "test", "test"

        def XPluginEnable(self):
            self.calls.append("enable")
            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    plugin = Plugin()
    mod = register_inline_plugin("headless_plugin", plugin)

    runner.run_plugin_lifecycle([mod])

    assert plugin.calls == ["start", "enable", "disable", "stop"]


# ===========================================================================
# 2. Headless plugin can create and use DataRefs
# ===========================================================================

def test_headless_plugin_dataref_usage():
    xp = FakeXP(debug=True, enable_gui=False)
    runner = SimlessRunner(xp, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    class Plugin:
        def __init__(self):
            self.value = None

        def XPluginStart(self):
            return "Test", "test", "test"

        def XPluginEnable(self):
            h = XPPython3.xp.findDataRef("sim/test/headless_value")
            XPPython3.xp.setDataf(h, 42.5)
            self.value = XPPython3.xp.getDataf(h)
            return 1

        def XPluginDisable(self):
            pass

        def XPluginStop(self):
            pass

    plugin = Plugin()
    mod = register_inline_plugin("headless_dataref_plugin", plugin)

    runner.run_plugin_lifecycle([mod])

    assert plugin.value == 42.5

    # Assert via public API
    h = xp.findDataRef("sim/test/headless_value")
    assert xp.getDataf(h) == 42.5


# ===========================================================================
# 3. Multiple headless plugins share DataRefs correctly
# ===========================================================================

def test_headless_shared_datarefs():
    xp = FakeXP(debug=True, enable_gui=False)
    runner = SimlessRunner(xp, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    class Writer:
        def __init__(self):
            self.calls = []

        def XPluginStart(self):
            self.calls.append("start")
            return "Writer", "writer", "writer"

        def XPluginEnable(self):
            self.calls.append("enable")
            h = xp.findDataRef("sim/test/shared_headless")
            xp.setDataf(h, 77.7)
            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    class Reader:
        def __init__(self):
            self.calls = []
            self.value = None

        def XPluginStart(self):
            self.calls.append("start")
            return "Reader", "reader", "reader"

        def XPluginEnable(self):
            self.calls.append("enable")
            h = xp.findDataRef("sim/test/shared_headless")
            self.value = xp.getDataf(h)
            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    writer = Writer()
    reader = Reader()

    mod_writer = register_inline_plugin("writer_headless", writer)
    mod_reader = register_inline_plugin("reader_headless", reader)

    runner.run_plugin_lifecycle([mod_writer, mod_reader])

    assert writer.calls == ["start", "enable", "disable", "stop"]
    assert reader.calls == ["start", "enable", "disable", "stop"]

    assert reader.value == 77.7

    # Assert via public API
    h = xp.findDataRef("sim/test/shared_headless")
    assert xp.getDataf(h) == 77.7


# ===========================================================================
# 4. GUI example test (headless)
# ===========================================================================

def test_example_gui():
    xp = FakeXP(debug=True, enable_gui=False)
    runner = SimlessRunner(xp, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    class DevOTAGUIPlugin:
        def __init__(self):
            self.calls = []
            self.win = None
            self.slider = None
            self.quit_btn = None

        def XPluginStart(self):
            self.calls.append("start")
            return "Dev OTA GUI", "simless.dev.ota.gui", "OTA GUI"

        def XPluginEnable(self):
            self.calls.append("enable")

            xp.registerDataRef(
                "sim/cockpit2/temperature/outside_air_temp_degc",
                xpType=2,
                isArray=False,
                writable=True,
                defaultValue=0.0,
            )

            self.win = xp.createWidget(
                100, 500, 500, 100, 1,
                "Simless OTA Control", 1, 0,
                xp.WidgetClass_MainWindow
            )

            xp.createWidget(
                120, 460, 480, 430, 1,
                "Adjust Outside Air Temperature (°C)",
                0, self.win, xp.WidgetClass_Caption
            )

            self.slider = xp.createWidget(
                120, 420, 480, 380, 1,
                "OAT Slider", 0, self.win,
                xp.WidgetClass_ScrollBar
            )

            xp.setWidgetProperty(self.slider, xp.Property_ScrollBarMin, -50)
            xp.setWidgetProperty(self.slider, xp.Property_ScrollBarMax, 50)
            xp.setWidgetProperty(self.slider, xp.Property_ScrollBarSliderPosition, 0)

            self.quit_btn = xp.createWidget(
                120, 340, 260, 300, 1,
                "Close", 0, self.win,
                xp.WidgetClass_Button
            )

            return 1

        def XPluginDisable(self):
            self.calls.append("disable")
            if self.win is not None:
                xp.killWidget(self.win)
                self.win = None

        def XPluginStop(self):
            self.calls.append("stop")

    plugin = DevOTAGUIPlugin()
    module_name = register_inline_plugin("dev_ota_gui_register_plugin", plugin)

    runner.run_plugin_lifecycle([module_name])

    assert plugin.calls == ["start", "enable", "disable", "stop"]

    handle = xp.findDataRef("sim/cockpit2/temperature/outside_air_temp_degc")
    assert xp.getDataf(handle) == 0.0

    assert plugin.slider is not None
    assert plugin.quit_btn is not None
    assert plugin.win is None
