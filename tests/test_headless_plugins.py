# tests/test_inline_plugins.py
# ===========================================================================
# Inline plugin tests using SimlessRunner + FakeXP
# Fully refactored to use the inline_plugin fixture
# ===========================================================================

import XPPython3

from sshd_extensions.bridge_protocol import BridgeData, BridgeDataType
from sshd_extensions.dataref_manager import DRefType
from simless.libs.fake_xp import FakeXP
from simless.libs.plugin_runner import SimlessRunner


# ===========================================================================
# 1. Basic headless plugin lifecycle
# ===========================================================================

def test_headless_plugin_lifecycle(inline_plugin):
    xp = FakeXP(debug=True, enable_gui=False)
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

    xp.simless_runner.run_plugin_lifecycle([mod], run_time=0.1)

    assert plugin.calls == ["start", "enable", "disable", "stop"]


# ===========================================================================
# 2. Headless plugin can create and use DataRefs
# ===========================================================================

def test_headless_plugin_dataref_usage(inline_plugin):
    xp = FakeXP(debug=True, enable_gui=False)
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

    xp.simless_runner.run_plugin_lifecycle([mod], run_time=0.1)

    assert plugin.value == 42.5

    # Assert via public API
    h = xp.findDataRef("sim/test/headless_value")
    assert xp.getDataf(h) == 42.5


# ===========================================================================
# 3. Multiple headless plugins share DataRefs correctly
# ===========================================================================

def test_headless_shared_datarefs(inline_plugin):
    xp = FakeXP(debug=True, enable_gui=False)
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

    xp.simless_runner.run_plugin_lifecycle([mod_writer, mod_reader], run_time=0.1)

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
                xp.destroyWidget(self.win)
                self.win = None

        def XPluginStop(self):
            self.calls.append("stop")

    plugin = DevOTAGUIPlugin()
    mod = inline_plugin(name="dev_ota_gui_register_plugin", plugin_obj=plugin)

    xp.simless_runner.run_plugin_lifecycle([mod], run_time=0.1)

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
    # 1. FakeXP in headless mode (bridge is runner-owned)
    # ----------------------------------------------------------------------
    xp = FakeXP(debug=True, enable_gui=False, enable_dataref_bridge=True)
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
    # 3. Pre-create the handle the runner expects to exist on META
    # ----------------------------------------------------------------------
    h0 = xp.findDataRef("sim/test/bridge_value")
    assert h0 is not None

    # ----------------------------------------------------------------------
    # 4. Fake bridge events
    # ----------------------------------------------------------------------
    meta_event = BridgeData(
        type=BridgeDataType.META,
        path="sim/test/bridge_value",
        dtype=DRefType.FLOAT,
        writable=True,
        array_size=0,
        value=None,
        text=None,
    )

    update_event = BridgeData(
        type=BridgeDataType.UPDATE,
        path="sim/test/bridge_value",
        dtype=DRefType.FLOAT,
        writable=True,
        array_size=0,
        value=123.45,
        text=None,
    )

    events = [meta_event, update_event]

    def fake_poll():
        nonlocal events
        out = events
        events = []
        return out

    # Bridge is runner-owned in headless mode
    runner = getattr(xp, "simless_runner", None)
    assert runner is not None, "FakeXP did not expose simless_runner"
    assert hasattr(runner, "_bridge"), "Runner has no _bridge"
    monkeypatch.setattr(runner._bridge, "poll_data", fake_poll)

    # ----------------------------------------------------------------------
    # 5. Run lifecycle
    # ----------------------------------------------------------------------
    runner.run_plugin_lifecycle([mod], run_time=0.1)

    # ----------------------------------------------------------------------
    # 6. Assertions
    # ----------------------------------------------------------------------
    h = xp.findDataRef("sim/test/bridge_value")
    assert xp.getDataf(h) == 123.45

    info = xp.getDataRefInfo(h)
    # XPLM-style bitmask, not DRefType enum
    assert int(info.type) != 0
