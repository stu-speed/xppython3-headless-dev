import sys
import types
import XPPython3

from simless.libs.fake_xp.fakexp import FakeXP
from simless.libs.fake_xp_runner import FakeXPRunner


def register_inline_plugin(name: str, plugin_obj) -> str:
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
# Dummy promotion test
# ===========================================================================

class DummyPlugin:
    def __init__(self):
        self.calls = []
        self.handle = None
        self.promoted_value = None

    def XPluginStart(self):
        self.calls.append("start")
        return "Dummy", "dummy", "dummy"

    def XPluginEnable(self):
        self.calls.append("enable")
        self.handle = XPPython3.xp.findDataRef("sim/test/auto_float")
        assert self.handle.dummy is True
        self.promoted_value = XPPython3.xp.getDataf(self.handle)
        return 1

    def XPluginDisable(self):
        self.calls.append("disable")

    def XPluginStop(self):
        self.calls.append("stop")


def test_dummy_promotion():
    xp = FakeXP(debug=True, enable_gui=False)
    runner = FakeXPRunner(xp, enable_gui=False, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    plugin = DummyPlugin()
    module_name = register_inline_plugin("dummy_plugin", plugin)

    runner.run_plugin_lifecycle([module_name])

    assert plugin.calls == ["start", "enable", "disable", "stop"]

    assert "sim/test/auto_float" in xp.datarefs._handles
    real = xp.datarefs._handles["sim/test/auto_float"]

    assert real.dummy is False
    assert xp.datarefs._values[real.path] == 0.0
    assert plugin.promoted_value == 0.0


# ===========================================================================
# Cross-plugin read/write test
# ===========================================================================

def test_cross_plugin_read_write():
    xp = FakeXP(debug=True, enable_gui=False)
    runner = FakeXPRunner(xp, enable_gui=False, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    class WriterPlugin:
        def __init__(self):
            self.calls = []

        def XPluginStart(self):
            self.calls.append("start")
            return "Writer", "writer", "writer"

        def XPluginEnable(self):
            self.calls.append("enable")
            h = XPPython3.xp.findDataRef("sim/test/shared")
            XPPython3.xp.setDataf(h, 123.456)
            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    class ReaderPlugin:
        def __init__(self):
            self.calls = []
            self.value = None

        def XPluginStart(self):
            self.calls.append("start")
            return "Reader", "reader", "reader"

        def XPluginEnable(self):
            self.calls.append("enable")
            h = XPPython3.xp.findDataRef("sim/test/shared")
            self.value = XPPython3.xp.getDataf(h)
            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    writer = WriterPlugin()
    reader = ReaderPlugin()

    mod_writer = register_inline_plugin("writer_plugin", writer)
    mod_reader = register_inline_plugin("reader_plugin", reader)

    runner.run_plugin_lifecycle([mod_writer, mod_reader])

    assert writer.calls == ["start", "enable", "disable", "stop"]
    assert reader.calls == ["start", "enable", "disable", "stop"]

    real = xp.datarefs._handles["sim/test/shared"]
    assert xp.datarefs._values[real.path] == 123.456
    assert reader.value == 123.456


# ===========================================================================
# Managed dataref notification test
# ===========================================================================

def test_managed_dataref_notification():
    xp = FakeXP(debug=True, enable_gui=False)
    runner = FakeXPRunner(xp, enable_gui=False, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    class MockManager:
        def __init__(self):
            self.notifications = []

        def _notify_dataref_changed(self, handle):
            self.notifications.append(handle)

    xp._dataref_manager = MockManager()

    class Plugin:
        def __init__(self):
            self.calls = []

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")
            h = XPPython3.xp.findDataRef("sim/test/managed")
            XPPython3.xp.setDataf(h, 9.99)
            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    plugin = Plugin()
    mod = register_inline_plugin("managed_plugin", plugin)

    runner.run_plugin_lifecycle([mod])

    assert plugin.calls == ["start", "enable", "disable", "stop"]

    real = xp.datarefs._handles["sim/test/managed"]

    assert xp._dataref_manager.notifications == [real, real]
    assert xp.datarefs._values[real.path] == 9.99


# ===========================================================================
# GUI example test (headless)
# ===========================================================================

def test_example_gui():
    xp = FakeXP(debug=True, enable_gui=False)
    runner = FakeXPRunner(xp, enable_gui=False, run_time=0.1)
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

    real = xp.datarefs._handles["sim/cockpit2/temperature/outside_air_temp_degc"]
    assert xp.datarefs._values[real.path] == 0.0

    assert plugin.slider is not None
    assert plugin.quit_btn is not None
    assert plugin.win is None
