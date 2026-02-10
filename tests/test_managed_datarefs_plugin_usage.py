import sys
import types
import XPPython3
import pytest

from sshd_extensions.datarefs import DataRefManager
from simless.libs.fake_xp import FakeXP
from simless.libs.runner import SimlessRunner


def register_plugin(name: str, plugin_obj) -> str:
    """
    Register a plugin instance as a PythonInterface module.
    """
    module = types.ModuleType(name)

    class PythonInterface:
        def __init__(self):
            self.instance = plugin_obj

        def XPluginStart(self):
            return self.instance.XPluginStart()

        def XPluginEnable(self):
            return self.instance.XPluginEnable()

        def XPluginDisable(self):
            return self.instance.XPluginDisable()

        def XPluginStop(self):
            return self.instance.XPluginStop()

    module.PythonInterface = PythonInterface
    sys.modules[name] = module
    return name


# ===========================================================================
# 1. Promotion: required managed DataRefs become real when available
# ===========================================================================

def test_managed_datarefs_promote_in_plugin():
    xp = FakeXP(debug=True, enable_gui=False)
    XPPython3.xp = xp
    runner = SimlessRunner(xp, run_time=0.3)
    xp._runner = runner

    class Plugin:
        def __init__(self):
            self.calls = []
            self.manager = DataRefManager(
                xp,
                {
                    "sim/test/oat": {"required": True, "default": 10.0},
                    "sim/test/bus": {"required": True, "default": [0.0] * 6},
                },
                timeout_seconds=5.0,
            )
            self.last_oat = None
            self.last_bus = None

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")
            self.floop = xp.createFlightLoop(self.flightloop)
            xp.scheduleFlightLoop(self.floop, -1)
            return 1

        def flightloop(self, since, elapsed, counter, refcon=None):
            # Mirror OTA plugin: gate on manager.ready(counter)
            if not self.manager.ready(counter):
                return 0.1

            self.last_oat = self.manager.get_value("sim/test/oat")
            self.last_bus = self.manager.get_value("sim/test/bus")
            return 0.1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    plugin = Plugin()
    mod = register_plugin("managed_plugin_test", plugin)

    # Pre-bind: FakeXP has not seen these DataRefs yet
    assert plugin.manager.specs["sim/test/oat"].is_dummy is True
    assert plugin.manager.specs["sim/test/bus"].is_dummy is True

    # Let the runner drive flightloops; FakeXP will auto-create DataRefs
    runner.run_plugin_lifecycle([mod])

    # After some frames, manager.ready(counter) should have promoted them
    oat_spec = plugin.manager.specs["sim/test/oat"]
    bus_spec = plugin.manager.specs["sim/test/bus"]

    assert oat_spec.is_dummy is False
    assert bus_spec.is_dummy is False

    # Values should now come from FakeXP (default float 0.0, default array [0.0]*6)
    assert plugin.last_oat == 0.0
    assert plugin.last_bus == [0.0] * 6


# ===========================================================================
# 2. Timeout: required DataRef never appears → plugin disabled
# ===========================================================================

def test_required_datarefs_timeout_disables_plugin(monkeypatch):
    xp = FakeXP(debug=True, enable_gui=False)
    XPPython3.xp = xp
    runner = SimlessRunner(xp, run_time=0.5)
    xp._runner = runner

    # Simulate "real XP never provides this DataRef"
    monkeypatch.setattr(xp, "findDataRef", lambda path: None)

    class Plugin:
        def __init__(self):
            self.calls = []
            self.manager = DataRefManager(
                xp,
                {
                    "sim/test/required": {"required": True, "default": 99.0},
                },
                timeout_seconds=0.3,
            )
            self.counter_seen = []

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")
            self.floop = xp.createFlightLoop(self.flightloop)
            xp.scheduleFlightLoop(self.floop, -1)
            return 1

        def flightloop(self, since, elapsed, counter, refcon=None):
            # Gate on manager.ready(counter); it will eventually timeout
            ready = self.manager.ready(counter)
            self.counter_seen.append((counter, ready))
            return 0.1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    plugin = Plugin()
    mod = register_plugin("required_timeout_plugin", plugin)

    runner.run_plugin_lifecycle([mod])

    # Manager should have timed out and disabled the plugin
    assert xp.isPluginEnabled(xp.getMyID()) == 0
    # We should have seen at least one "not ready" state
    assert any(not r for _, r in plugin.counter_seen)


# ===========================================================================
# 3. Optional DataRef: never disables plugin, returns default until bound
# ===========================================================================

def test_optional_dataref_never_disables_plugin(monkeypatch):
    xp = FakeXP(debug=True, enable_gui=False)
    XPPython3.xp = xp
    runner = SimlessRunner(xp, run_time=0.3)
    xp._runner = runner

    # Simulate "real XP never provides this DataRef"
    monkeypatch.setattr(xp, "findDataRef", lambda path: None)

    class Plugin:
        def __init__(self):
            self.calls = []
            self.manager = DataRefManager(
                xp,
                {
                    "sim/test/optional": {"required": False, "default": 55.0},
                },
                timeout_seconds=0.3,
            )
            self.values = []

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")
            self.floop = xp.createFlightLoop(self.flightloop)
            xp.scheduleFlightLoop(self.floop, -1)
            return 1

        def flightloop(self, since, elapsed, counter, refcon=None):
            # Optional refs: ready() may stay False, but plugin must not be disabled
            self.manager.ready(counter)
            self.values.append(self.manager.get_value("sim/test/optional"))
            return 0.1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    plugin = Plugin()
    mod = register_plugin("optional_plugin", plugin)

    runner.run_plugin_lifecycle([mod])

    # Plugin must remain enabled (manager must not disable on optional timeout)
    assert xp.isPluginEnabled(xp.getMyID()) == 1
    # All values should be the default, since the DataRef never bound
    assert plugin.values
    assert all(v == 55.0 for v in plugin.values)


# ===========================================================================
# 4. Flightloop gating: no use of values until ready() is True
# ===========================================================================

def test_flightloop_gates_on_ready():
    xp = FakeXP(debug=True, enable_gui=False)
    XPPython3.xp = xp
    runner = SimlessRunner(xp, run_time=0.3)
    xp._runner = runner

    class Plugin:
        def __init__(self):
            self.calls = []
            self.manager = DataRefManager(
                xp,
                {
                    "sim/test/oat": {"required": True, "default": 10.0},
                },
                timeout_seconds=5.0,
            )
            self.ready_seen = []
            self.values = []

        def XPluginStart(self):
            self.calls.append("start")
            return "P", "p", "p"

        def XPluginEnable(self):
            self.calls.append("enable")
            self.floop = xp.createFlightLoop(self.flightloop)
            xp.scheduleFlightLoop(self.floop, -1)
            return 1

        def flightloop(self, since, elapsed, counter, refcon=None):
            r = self.manager.ready(counter)
            self.ready_seen.append(r)
            if not r:
                return 0.1
            self.values.append(self.manager.get_value("sim/test/oat"))
            return 0.1

        def XPluginDisable(self):
            self.calls.append("disable")

        def XPluginStop(self):
            self.calls.append("stop")

    plugin = Plugin()
    mod = register_plugin("gated_flightloop_plugin", plugin)

    runner.run_plugin_lifecycle([mod])

    # We must have seen at least one "not ready" and at least one "ready"
    assert any(not r for r in plugin.ready_seen)
    assert any(r for r in plugin.ready_seen)
    # Once ready, values should be real XP values (0.0 from FakeXP)
    assert plugin.values
    assert all(v == 0.0 for v in plugin.values)


# ===========================================================================
# 5. Enum keys: MDR-style usage
# ===========================================================================

def test_plugin_enum_keys():
    xp = FakeXP(debug=True, enable_gui=False)
    XPPython3.xp = xp
    runner = SimlessRunner(xp, run_time=0.2)
    xp._runner = runner

    class MDR(str, __import__("enum").Enum):
        oat_c = "sim/test/oat_enum"
        bus_volts = "sim/test/bus_enum"

    class Plugin:
        def __init__(self):
            self.manager = DataRefManager(
                xp,
                {
                    MDR.oat_c: {"required": True, "default": 10.0},
                    MDR.bus_volts: {"required": True, "default": [0.0] * 6},
                },
                timeout_seconds=5.0,
            )
            self.values = []

        def XPluginStart(self):
            return "P", "p", "p"

        def XPluginEnable(self):
            self.floop = xp.createFlightLoop(self.flightloop)
            xp.scheduleFlightLoop(self.floop, -1)
            return 1

        def flightloop(self, since, elapsed, counter, refcon=None):
            if not self.manager.ready(counter):
                return 0.1
            self.values.append(
                (
                    self.manager.get_value(MDR.oat_c),
                    self.manager.get_value(MDR.bus_volts),
                )
            )
            return 0.1

        def XPluginDisable(self):
            pass

        def XPluginStop(self):
            pass

    plugin = Plugin()
    mod = register_plugin("enum_plugin", plugin)

    runner.run_plugin_lifecycle([mod])

    # Enum keys must resolve to their string paths and bind correctly
    assert plugin.values
    for oat, bus in plugin.values:
        assert oat == 0.0
        assert bus == [0.0] * 6
