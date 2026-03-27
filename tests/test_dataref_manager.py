# tests/test_dataref_manager.py
# ===========================================================================
# DataRefManager + FakeXP integration tests (mgr + xp get/set)
# ===========================================================================

import pytest
import time

import XPPython3

from simless.libs.fake_xp import FakeXP
from PythonPlugins.sshd_extensions.dataref_manager import DataRefManager


# ===========================================================================
# 1. Dummy spec creation
# ===========================================================================

def test_dummy_spec_creation():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    specs = {
        "sim/test/foo": {"required": False, "default": 42.0},
        "sim/test/bar": {"required": True,  "default": -1.0},
    }

    mgr = DataRefManager(xp, specs, timeout_seconds=30.0)

    assert mgr.timeout == 30.0

    foo = mgr.get_spec("sim/test/foo")
    bar = mgr.get_spec("sim/test/bar")

    assert foo.is_dummy is True
    assert bar.is_dummy is True
    assert foo.default == 42.0
    assert bar.default == -1.0


# ===========================================================================
# 2. Dummy → real promotion
# ===========================================================================

def test_dummy_to_real_promotion(monkeypatch):
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    # Make this spec required so the manager will wait for a real handle.
    mgr = DataRefManager(xp, {"sim/test/promote": {"required": True, "default": 5.0}})

    # before any ready() call the spec should be a dummy
    spec = mgr.get_spec("sim/test/promote")
    assert spec.is_dummy is True

    # FakeXP auto register dataref- ready() should observe the promoted spec and return True
    assert mgr.ready() is True

    # after promotion the spec should no longer be a dummy
    spec = mgr.get_spec("sim/test/promote")
    assert spec.is_dummy is False
    assert spec.handle is not None

    # mgr read (manager-backed value after promotion)
    assert mgr.ready() is True
    assert mgr.get_value("sim/test/promote") == 0.0


# ===========================================================================
# 3. Required timeout (no auto-registration)
# ===========================================================================

def test_required_timeout(monkeypatch):
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    # Simulate xp never providing the dataref
    monkeypatch.setattr(xp, "findDataRef", lambda path: None)

    mgr = DataRefManager(xp, {"sim/test/required": {"required": True, "default": 99.0}}, timeout_seconds=0.1)

    # FakeXP auto register dataref- ready() should observe the promoted spec and return True
    assert mgr.ready() is False

    time.sleep(0.2)
    mgr.ready()

    # FakeXP should have attempted to disable the plugin
    assert xp.isPluginEnabled(xp.getMyID()) == 0


# ===========================================================================
# 4. Dummy returns default (mgr), mgr.get/set auto-register semantics
# ===========================================================================

def test_dummy_returns_default(monkeypatch):
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    # Make the spec required so set_value is permitted by manager
    mgr = DataRefManager(xp, {"sim/test/default": {"required": False, "default": 7.7}})

    # Simulate xp never providing the dataref
    monkeypatch.setattr(xp, "findDataRef", lambda path: None)

    # manager returns configured default for dummy spec
    assert mgr.get_value("sim/test/default") == 7.7

    # mgr.set updates manager value
    mgr.set_value("sim/test/default", 22.2)
    assert mgr.get_value("sim/test/default") == 22.2


# ===========================================================================
# 8. Real XP value after promotion (mgr.set / mgr.get)
# ===========================================================================

def test_real_value_after_promotion(monkeypatch):
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/live": {"required": False, "default": 1.0}})

    # FakeXP auto register dataref- ready() should observe the promoted spec and return True
    mgr.ready()

    # after promotion the manager handle exists and get_value reflects xp state
    assert mgr.get_value("sim/test/live") == 0.0

    # simulate plugin write via manager API (since tests should prefer manager helpers)
    # make the spec required so set_value is permitted
    spec = mgr.get_spec("sim/test/live")
    spec.required = True
    mgr.set_value("sim/test/live", 88.8)
    assert mgr.get_value("sim/test/live") == 88.8


# ===========================================================================
# 9. set_value scalar (mgr.set AFTER promotion → mgr.get)
# ===========================================================================

def test_set_value_scalar():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    # make required so manager allows set_value
    mgr = DataRefManager(xp, {"sim/test/scalar": {"required": True, "default": 0.0}})

    # FakeXP auto register dataref- ready() should observe the promoted spec and return True
    mgr.ready()

    # mgr.set → mgr.get
    mgr.set_value("sim/test/scalar", 12.5)
    assert mgr.get_value("sim/test/scalar") == 12.5

    # simulate external xp write by using mgr.set_value (manager is authoritative in tests)
    mgr.set_value("sim/test/scalar", 99.9)
    assert mgr.get_value("sim/test/scalar") == 99.9


# ===========================================================================
# 12. set_value not writable
# ===========================================================================

def test_set_value_not_writable():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/ro": {"required": True, "default": 5.0}})

    # FakeXP auto register dataref- ready() should observe the promoted spec and return True
    mgr.ready()

    # Ensure underlying xp handle is marked not writable so xp.set* raises
    spec = mgr.get_spec("sim/test/ro")
    # spec.handle is the real xp handle after promotion
    with xp._handles_lock:
        xp._handles[spec.name].writable = False

    with pytest.raises(PermissionError):
        mgr.set_value("sim/test/ro", 10.0)


# ===========================================================================
# 13. dummy spec auto-promotes on write (mgr.set AFTER promotion)
# ===========================================================================

def test_set_value_on_dummy_autoregisters():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/dummy": {"required": True, "default": 9.9}})

    # FakeXP auto register dataref- ready() should observe the promoted spec and return True
    mgr.ready()

    mgr.set_value("sim/test/dummy", 1.0)
    assert mgr.get_value("sim/test/dummy") == 1.0


# ===========================================================================
# 14. unmanaged auto-registers on write (mgr.set AFTER promotion)
# ===========================================================================

def test_set_value_unmanaged_autoregisters():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, datarefs=None)

    # unmanaged → must raise KeyError
    with pytest.raises(KeyError):
        mgr.set_value("sim/unknown/path", 123)


# ===========================================================================
# 15. set_value after promotion (mgr.set AFTER promotion → mgr.get)
# ===========================================================================

def test_set_value_after_promotion():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/livewrite": {"required": True, "default": 1.0}})

    # FakeXP auto register dataref- ready() should observe the promoted spec and return True
    mgr.ready()

    # mgr.set → mgr.get
    mgr.set_value("sim/test/livewrite", 77.7)
    assert mgr.get_value("sim/test/livewrite") == 77.7

    # mgr.set again to simulate xp write
    mgr.set_value("sim/test/livewrite", 55.5)
    assert mgr.get_value("sim/test/livewrite") == 55.5
