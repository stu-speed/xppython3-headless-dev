# tests/test_datarefs.py
# ===========================================================================
# DataRefManager + FakeXP integration tests (mgr + xp get/set)
# ===========================================================================

import pytest
import XPPython3

from simless.libs.fake_xp import FakeXP
from sshd_extensions.datarefs import DataRefSpec, DataRefManager


# ===========================================================================
# 1. Dummy spec creation
# ===========================================================================

def test_dummy_spec_creation():
    xp = FakeXP(debug=True, run_time=.01)
    XPPython3.xp = xp

    specs = {
        "sim/test/foo": {"required": False, "default": 42.0},
        "sim/test/bar": {"required": True,  "default": -1.0},
    }

    mgr = DataRefManager(xp, specs, timeout_seconds=30.0)

    assert xp._dataref_manager is mgr
    assert mgr.timeout == 30.0

    foo = mgr.specs["sim/test/foo"]
    bar = mgr.specs["sim/test/bar"]

    assert foo.is_dummy is True
    assert bar.is_dummy is True
    assert foo.default == 42.0
    assert bar.default == -1.0


# ===========================================================================
# 1b. Specs merged + timeout max
# ===========================================================================

def test_merged_specs_and_timeout():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr1 = DataRefManager(xp, {"sim/test/a": {"required": False, "default": 1.0}}, timeout_seconds=5.0)
    mgr2 = DataRefManager(xp, {"sim/test/b": {"required": True,  "default": 2.0}}, timeout_seconds=30.0)

    assert mgr1 is mgr2
    assert "sim/test/a" in mgr1.specs
    assert "sim/test/b" in mgr1.specs
    assert mgr1.timeout == 30.0


# ===========================================================================
# 2. Dummy → real promotion
# ===========================================================================

def test_dummy_to_real_promotion():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/promote": {"required": False, "default": 5.0}})

    assert mgr.ready(0) is False
    assert mgr.ready(1) is True

    spec = mgr.specs["sim/test/promote"]
    assert spec.is_dummy is False
    assert spec.handle is not None

    # mgr read
    assert mgr.get_value("sim/test/promote") == 0.0

    # xp read
    h = xp.findDataRef("sim/test/promote")
    assert xp.getDataf(h) == 0.0


# ===========================================================================
# 3. Required timeout (no auto-registration)
# ===========================================================================

def test_required_timeout(monkeypatch):
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    monkeypatch.setattr(xp, "findDataRef", lambda path: None)

    mgr = DataRefManager(xp, {"sim/test/required": {"required": True, "default": 99.0}}, timeout_seconds=0.1)

    assert mgr.ready(0) is False

    for i in range(1, 200):
        mgr.ready(i)

    assert xp.isPluginEnabled(xp.getMyID()) == 0


# ===========================================================================
# 4. Required no-timeout (FakeXP auto-register)
# ===========================================================================

def test_required_no_timeout():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/required": {"required": True, "default": 123.0}}, timeout_seconds=0.1)

    assert mgr.ready(0) is False

    for i in range(1, 50):
        mgr.ready(i)

    assert xp.isPluginEnabled(xp.getMyID()) == 1
    assert mgr.get_value("sim/test/required") == 0.0


# ===========================================================================
# 5. Unmanaged DataRef: xp.get + xp.set auto-register
# ===========================================================================

def test_unmanaged_dataref_returns_none():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, datarefs=None)

    # mgr has no spec → None
    assert mgr.get_value("sim/unknown/path") is None

    # xp.get auto-registers
    h = xp.findDataRef("sim/unknown/path")
    assert xp.getDataf(h) == 0.0

    # xp.set updates
    xp.setDataf(h, 55.5)
    assert xp.getDataf(h) == 55.5


# ===========================================================================
# 6. Dummy returns default (mgr), xp.get + xp.set auto-register
# ===========================================================================

def test_dummy_returns_default():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/default": {"required": False, "default": 7.7}})

    assert mgr.get_value("sim/test/default") == 7.7

    # xp.get auto-registers
    h = xp.findDataRef("sim/test/default")
    assert xp.getDataf(h) == 0.0

    # xp.set updates
    xp.setDataf(h, 22.2)
    assert xp.getDataf(h) == 22.2


# ===========================================================================
# 7. Manual dummy spec works (mgr), xp.get + xp.set auto-register
# ===========================================================================

def test_headless_auto_manage():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, datarefs=None)

    mgr.specs["sim/test/auto"] = DataRefSpec.dummy("sim/test/auto", required=False, default=55.0)

    assert mgr.get_value("sim/test/auto") == 55.0

    # xp.get auto-registers
    h = xp.findDataRef("sim/test/auto")
    assert xp.getDataf(h) == 0.0

    # xp.set updates
    xp.setDataf(h, 44.4)
    assert xp.getDataf(h) == 44.4


# ===========================================================================
# 8. Real XP value after promotion (xp.set → mgr.get)
# ===========================================================================

def test_real_value_after_promotion(monkeypatch):
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/live": {"required": False, "default": 1.0}})

    monkeypatch.setattr(mgr, "_notify_dataref_changed", lambda *a, **k: None, raising=False)

    mgr.ready(0)
    mgr.ready(1)

    h = xp.findDataRef("sim/test/live")
    xp.setDataf(h, 88.8)

    assert mgr.get_value("sim/test/live") == 88.8


# ===========================================================================
# 9. set_value scalar (mgr.set AFTER promotion → xp.get, xp.set → mgr.get)
# ===========================================================================

def test_set_value_scalar():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/scalar": {"required": False, "default": 0.0}})

    # Promote first
    mgr.ready(0)
    mgr.ready(1)

    # mgr.set → xp.get
    mgr.set_value("sim/test/scalar", 12.5)
    h = xp.findDataRef("sim/test/scalar")
    assert xp.getDataf(h) == 12.5

    # xp.set → mgr.get
    xp.setDataf(h, 99.9)
    assert mgr.get_value("sim/test/scalar") == 99.9


# ===========================================================================
# 10. set_value array (mgr.set AFTER promotion → xp.get, xp.set → mgr.get)
# ===========================================================================

def test_set_value_array_float():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/arr": {"required": False, "default": [0.0, 0.0, 0.0]}})

    # Promote first
    mgr.ready(0)
    mgr.ready(1)

    # mgr.set → xp.get
    mgr.set_value("sim/test/arr", [1.1, 2.2, 3.3])
    h = xp.findDataRef("sim/test/arr")
    out = [0.0, 0.0, 0.0]
    xp.getDatavf(h, out, 0, 3)
    assert out == [1.1, 2.2, 3.3]

    # xp.set → mgr.get
    xp.setDatavf(h, [9.9, 8.8, 7.7], 0, 3)
    assert mgr.get_value("sim/test/arr") == [9.9, 8.8, 7.7]


# ===========================================================================
# 11. set_value wrong array size
# ===========================================================================

def test_set_value_wrong_size_raises():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/arr": {"required": False, "default": [0.0, 0.0]}})

    # Promote first
    mgr.ready(0)
    mgr.ready(1)

    with pytest.raises(ValueError):
        mgr.set_value("sim/test/arr", [1.0, 2.0, 3.0])


# ===========================================================================
# 12. set_value not writable
# ===========================================================================

def test_set_value_not_writable():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/ro": {"required": False, "default": 5.0}})

    # Promote first
    mgr.ready(0)
    mgr.ready(1)

    mgr.set_value("sim/test/ro", 5.0)

    spec = mgr.specs["sim/test/ro"]
    spec.writable = False

    with pytest.raises(PermissionError):
        mgr.set_value("sim/test/ro", 10.0)


# ===========================================================================
# 13. dummy spec auto-promotes on write (mgr.set AFTER promotion)
# ===========================================================================

def test_set_value_on_dummy_autoregisters():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/dummy": {"required": False, "default": 9.9}})

    # Promote first
    mgr.ready(0)
    mgr.ready(1)

    mgr.set_value("sim/test/dummy", 1.0)
    assert mgr.get_value("sim/test/dummy") == 1.0

    h = xp.findDataRef("sim/test/dummy")
    assert xp.getDataf(h) == 1.0


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
# 15. set_value after promotion (mgr.set AFTER promotion → xp.get, xp.set → mgr.get)
# ===========================================================================

def test_set_value_after_promotion():
    xp = FakeXP(debug=True)
    XPPython3.xp = xp

    mgr = DataRefManager(xp, {"sim/test/livewrite": {"required": False, "default": 1.0}})

    # Promote first
    mgr.ready(0)
    mgr.ready(1)

    # mgr.set → xp.get
    mgr.set_value("sim/test/livewrite", 77.7)
    h = xp.findDataRef("sim/test/livewrite")
    assert xp.getDataf(h) == 77.7

    # xp.set → mgr.get
    xp.setDataf(h, 55.5)
    assert mgr.get_value("sim/test/livewrite") == 55.5
