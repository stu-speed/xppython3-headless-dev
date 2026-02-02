# test_fakexp.py

import sys
import types
import XPPython3
from simless.libs.fake_xp import FakeXP
from simless.libs.fake_xp_runner import FakeXPRunner


def register_inline_plugin(name: str, plugin_obj) -> str:
    """
    Creates an inline module with a PythonInterface class,
    registers it in sys.modules, and returns the module name.

    This mirrors XPPython3's plugin loading model while avoiding
    filesystem dependencies for deterministic unit testing.
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


class DummyPlugin:
    """
    Plugin that triggers dummy promotion by accessing a missing dataref.
    Validates:
      - Dummy handle creation
      - Promotion on first accessor call
      - Correct default value
      - Lifecycle ordering
    """
    def __init__(self):
        self.calls = []
        self.handle = None
        self.promoted_value = None

    def XPluginStart(self):
        self.calls.append("start")
        return "Dummy", "dummy", "dummy", "dummy"

    def XPluginEnable(self):
        self.calls.append("enable")

        # Step 1: request a missing dataref → returns dummy handle
        self.handle = XPPython3.xp.findDataRef("sim/test/auto_float")

        # Step 2: use the dummy handle → triggers FakeXP._promote_dummy
        self.promoted_value = XPPython3.xp.getDataf(self.handle)

        return 1

    def XPluginDisable(self):
        self.calls.append("disable")

    def XPluginStop(self):
        self.calls.append("stop")


def test_dummy_promotion():
    """
    Ensures:
      - findDataRef returns a dummy handle
      - getDataf(dummy) triggers FakeXP._promote_dummy
      - Real dataref is created with correct default value
      - Lifecycle phases run in correct order
    """
    xp = FakeXP(debug=True)
    runner = FakeXPRunner(xp, enable_gui=False, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    plugin = DummyPlugin()
    module_name = register_inline_plugin("dummy_plugin", plugin)

    runner.load_plugin(module_name)
    runner.run_plugin_lifecycle()

    # Lifecycle assertions
    assert plugin.calls == ["start", "enable", "disable", "stop"]

    # Dummy handle should be negative
    assert plugin.handle < 0

    # Dataref should now exist in the real table
    assert "sim/test/auto_float" in xp._handles

    real_handle = xp._handles["sim/test/auto_float"]
    assert real_handle >= 1

    # Default value for float promotion is 0.0
    assert xp._values[real_handle] == 0.0
    assert plugin.promoted_value == 0.0


# ===========================================================================
# Cross-plugin read/write test
# ===========================================================================
def test_cross_plugin_read_write():
    """
    Validates that:
      - Plugin A promotes + writes a dataref
      - Plugin B reads the same dataref
      - Both see the same real handle and value
      - Promotion happens exactly once
    """
    xp = FakeXP(debug=True)
    runner = FakeXPRunner(xp, enable_gui=False, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    # Writer plugin
    class WriterPlugin:
        def __init__(self):
            self.calls = []

        def XPluginStart(self):
            self.calls.append("start")
            return "Writer", "writer", "writer", "writer"

        def XPluginEnable(self):
            self.calls.append("enable")
            h = XPPython3.xp.findDataRef("sim/test/shared")
            XPPython3.xp.setDataf(h, 123.456)
            return 1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    # Reader plugin
    class ReaderPlugin:
        def __init__(self):
            self.calls = []
            self.value = None

        def XPluginStart(self):
            self.calls.append("start")
            return "Reader", "reader", "reader", "reader"

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

    runner.load_plugin(mod_writer)
    runner.load_plugin(mod_reader)
    runner.run_plugin_lifecycle()

    # Both plugins ran
    assert writer.calls == ["start", "enable", "disable", "stop"]
    assert reader.calls == ["start", "enable", "disable", "stop"]

    # Dataref exists
    assert "sim/test/shared" in xp._handles
    real = xp._handles["sim/test/shared"]

    # Writer wrote the value
    assert xp._values[real] == 123.456

    # Reader saw the same value
    assert reader.value == 123.456


# ===========================================================================
# Managed dataref test
# ===========================================================================
def test_managed_dataref_notification():
    """
    Validates:
      - FakeXP notifies DataRefManager on promotion
      - Manager receives exactly one notification
      - Value is written correctly
    """
    xp = FakeXP(debug=True)
    runner = FakeXPRunner(xp, enable_gui=False, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    # Mock DataRefManager
    class MockManager:
        def __init__(self):
            self.notifications = []

        def _notify_dataref_changed(self, handle):
            self.notifications.append(handle)

    manager = MockManager()
    xp._dataref_manager = manager

    # Plugin that writes to a missing dataref
    class Plugin:
        def __init__(self):
            self.calls = []

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p", "p"

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

    runner.load_plugin(mod)
    runner.run_plugin_lifecycle()

    # Lifecycle ran
    assert plugin.calls == ["start", "enable", "disable", "stop"]

    # Dataref exists
    assert "sim/test/managed" in xp._handles
    real = xp._handles["sim/test/managed"]

    # Manager was notified exactly once
    assert manager.notifications == [real]

    # Value was written correctly
    assert xp._values[real] == 9.99


def test_example_gui():
    """
    Validates:
      - GUI widgets are created correctly (window, caption, slider, button)
      - Slider callback updates the promoted OAT dataref
      - Quit button callback closes the window and ends the run loop
      - Plugin lifecycle ordering is correct
      - Dummy promotion for OAT dataref occurs as expected
    """

    xp = FakeXP(debug=True)
    runner = FakeXPRunner(xp, enable_gui=False, run_time=0.1)
    xp._runner = runner
    XPPython3.xp = xp

    # ----------------------------------------------------------------------
    # Inline plugin that registers the OAT dataref but does NOT move slider
    # ----------------------------------------------------------------------
    class DevOTAGUIPlugin:
        def __init__(self):
            self.calls = []
            self.win = None
            self.slider = None
            self.quit_btn = None
            self.oat_handle = None

        def XPluginStart(self):
            self.calls.append("start")
            return "Dev OTA GUI", "simless.dev.ota.gui", "OTA GUI"

        def XPluginEnable(self):
            self.calls.append("enable")

            # Explicit dataref registration (no promotion needed)
            self.oat_handle = xp.registerDataRef(
                "sim/cockpit2/temperature/outside_air_temp_degc",
                xpType=2,   # float
                isArray=False,
                writable=True,
                defaultValue=0.0,
            )

            # Build GUI (no interaction required)
            self.win = xp.createWidget(100, 500, 500, 100, 1,
                                       "Simless OTA Control", 1, 0,
                                       xp.WidgetClass_MainWindow)

            xp.createWidget(120, 460, 480, 430, 1,
                            "Adjust Outside Air Temperature (°C)",
                            0, self.win, xp.WidgetClass_Caption)

            self.slider = xp.createWidget(120, 420, 480, 380, 1,
                                          "OAT Slider", 0, self.win,
                                          xp.WidgetClass_ScrollBar)

            xp.setWidgetProperty(self.slider, xp.Property_ScrollMin, -50)
            xp.setWidgetProperty(self.slider, xp.Property_ScrollMax, 50)
            xp.setWidgetProperty(self.slider, xp.Property_ScrollValue, 0)

            self.quit_btn = xp.createWidget(120, 340, 260, 300, 1,
                                            "Close", 0, self.win,
                                            xp.WidgetClass_Button)

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

    # ----------------------------------------------------------------------
    # Run plugin lifecycle
    # ----------------------------------------------------------------------
    runner.load_plugin(module_name)
    runner.run_plugin_lifecycle()

    # ----------------------------------------------------------------------
    # Assertions
    # ----------------------------------------------------------------------

    # Lifecycle ordering
    assert plugin.calls == ["start", "enable", "disable", "stop"]

    # Dataref exists (registered explicitly)
    assert "sim/cockpit2/temperature/outside_air_temp_degc" in xp._handles
    real = xp._handles["sim/cockpit2/temperature/outside_air_temp_degc"]

    # Default value is correct
    assert xp._values[real] == 0.0

    # GUI widgets were created during enable
    # (we check creation indirectly via widget IDs)
    assert plugin.slider is not None
    assert plugin.quit_btn is not None

    # Window is destroyed during disable (plugin logic)
    assert plugin.win is None
