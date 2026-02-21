# tests/test_inline_plugins.py
# ===========================================================================
# Inline plugin tests using SimlessRunner + FakeXP
# Fully refactored to use the inline_plugin fixture
# ===========================================================================

import XPPython3

from sshd_extensions.bridge_protocol import BridgeData, BridgeDataType
from sshd_extensions.datarefs import DRefType
from simless.libs.fake_xp import FakeXP
from simless.libs.runner import SimlessRunner


# ===========================================================================
# 1. Basic headless plugin lifecycle
# ===========================================================================

def test_headless_plugin_lifecycle(inline_plugin):
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
    mod = inline_plugin(name="headless_plugin", plugin_obj=plugin)

    runner.run_plugin_lifecycle([mod])

    assert plugin.calls == ["start", "enable", "disable", "stop"]


# ===========================================================================
# 2. Headless plugin can create and use DataRefs
# ===========================================================================

def test_headless_plugin_dataref_usage(inline_plugin):
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
    mod = inline_plugin(name="headless_dataref_plugin", plugin_obj=plugin)

    runner.run_plugin_lifecycle([mod])

    assert plugin.value == 42.5

    # Assert via public API
    h = xp.findDataRef("sim/test/headless_value")
    assert xp.getDataf(h) == 42.5


# ===========================================================================
# 3. Multiple headless plugins share DataRefs correctly
# ===========================================================================

def test_headless_shared_datarefs(inline_plugin):
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

    mod_writer = inline_plugin(name="writer_headless", plugin_obj=writer)
    mod_reader = inline_plugin(name="reader_headless", plugin_obj=reader)

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

def test_example_gui(inline_plugin):
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
    mod = inline_plugin(name="dev_ota_gui_register_plugin", plugin_obj=plugin)

    runner.run_plugin_lifecycle([mod])

    assert plugin.calls == ["start", "enable", "disable", "stop"]

    handle = xp.findDataRef("sim/cockpit2/temperature/outside_air_temp_degc")
    assert xp.getDataf(handle) == 0.0

    assert plugin.slider is not None
    assert plugin.quit_btn is not None
    assert plugin.win is None

# ===========================================================================
# 5. Validate that FakeXP + SimlessRunner correctly process bridge META/UPDATE
# ===========================================================================

def test_headless_bridge_enabled(inline_plugin, monkeypatch):
    # ----------------------------------------------------------------------
    # 1. FakeXP in headless mode with bridge enabled
    # ----------------------------------------------------------------------
    xp = FakeXP(debug=True, enable_gui=False, enable_dataref_bridge=True)
    runner = SimlessRunner(xp, run_time=0.1)
    XPPython3.xp = xp

    # ----------------------------------------------------------------------
    # 2. Inline plugin (does nothing except allow lifecycle to run)
    # ----------------------------------------------------------------------
    class Plugin:
        def XPluginStart(self):
            return "BridgeTest", "bridge.test", "Bridge test"

        def XPluginEnable(self):
            return 1

        def XPluginDisable(self):
            pass

        def XPluginStop(self):
            pass

    mod = inline_plugin(name="bridge_test_plugin", plugin_obj=Plugin())

    # ----------------------------------------------------------------------
    # 3. Fake bridge events
    # ----------------------------------------------------------------------
    # META: define real DataRef metadata
    meta_event = BridgeData(
        type=BridgeDataType.META,
        path="sim/test/bridge_value",
        dtype=DRefType.FLOAT,
        writable=True,
        array_size=0,
        value=None,
        text=None,
    )

    # UPDATE: set actual value
    update_event = BridgeData(
        type=BridgeDataType.UPDATE,
        path="sim/test/bridge_value",
        dtype=DRefType.FLOAT,
        writable=True,
        array_size=0,
        value=123.45,
        text=None,
    )

    # Monkeypatch bridge.poll_data() to return META then UPDATE
    events = [meta_event, update_event]

    def fake_poll():
        # Return all events once, then nothing
        nonlocal events
        out = events
        events = []
        return out

    monkeypatch.setattr(runner.bridge, "poll_data", fake_poll)

    # ----------------------------------------------------------------------
    # 4. Run lifecycle
    # ----------------------------------------------------------------------
    runner.run_plugin_lifecycle([mod])

    # ----------------------------------------------------------------------
    # 5. Assertions
    # ----------------------------------------------------------------------
    mgr = xp._dataref_manager
    spec = mgr.get_spec("sim/test/bridge_value")

    # META should have created a real spec
    assert spec is not None
    assert spec.is_dummy is False
    assert spec.writable is True
    assert spec.type == DRefType.FLOAT

    # UPDATE should have set the value
    assert mgr.get_value("sim/test/bridge_value") == 123.45

    # Public API should reflect the same value
    h = xp.findDataRef("sim/test/bridge_value")
    assert xp.getDataf(h) == 123.45
