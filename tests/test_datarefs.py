# tests/test_datarefs.py
# ===========================================================================
# DataRefManager + FakeXP integration tests
# ===========================================================================

import pytest
import XPPython3

from simless.libs.fake_xp import FakeXP
from sshd_extensions.datarefs import DataRefManager, DataRefSpec


# ===========================================================================
# Helpers
# ===========================================================================

class DummyXP(FakeXP):
    """
    FakeXP with GUI disabled for tests.
    """
    def __init__(self, **kwargs):
        super().__init__(debug=True, enable_gui=False, **kwargs)


def make_manager(xp, specs=None):
    return DataRefManager(xp, datarefs=specs)


# ===========================================================================
# 1. Dummy spec creation
# ===========================================================================

def test_dummy_spec_creation():
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {
        "sim/test/foo": {"required": False, "default": 42.0},
        "sim/test/bar": {"required": True,  "default": -1.0},
    }

    mgr = make_manager(xp, specs)

    foo = mgr.specs["sim/test/foo"]
    bar = mgr.specs["sim/test/bar"]

    assert foo.is_dummy is True
    assert bar.is_dummy is True
    assert foo.default == 42.0
    assert bar.default == -1.0


# ===========================================================================
# 2. Dummy → real promotion
# ===========================================================================

def test_dummy_to_real_promotion():
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {"sim/test/promote": {"required": False, "default": 5.0}}
    mgr = make_manager(xp, specs)

    assert mgr.ready(0) is False
    assert mgr.ready(1) is True

    spec = mgr.specs["sim/test/promote"]
    assert spec.is_dummy is False
    assert spec.handle is not None
    assert mgr.get_value("sim/test/promote") == 0.0


# ===========================================================================
# 3. Required DataRef timeout (no bridge)
# ===========================================================================

def test_required_timeout(monkeypatch):
    xp = DummyXP()
    XPPython3.xp = xp

    # Simulate real XP: missing DataRefs return None
    monkeypatch.setattr(xp, "findDataRef", lambda path: None)

    specs = {"sim/test/required": {"required": True, "default": 99.0}}
    mgr = make_manager(xp, specs)

    assert mgr.ready(0) is False

    for i in range(1, 20):
        mgr.ready(i)

    # Required DataRef never resolved → plugin disabled
    assert xp.isPluginEnabled(xp.getMyID()) == 0


# ===========================================================================
# 4. Required DataRef does NOT timeout when FakeXP auto-registers
# ===========================================================================

def test_required_no_timeout(monkeypatch):
    xp = DummyXP()
    XPPython3.xp = xp

    # Allow FakeXP auto-generation
    monkeypatch.setattr(xp, "_handles", {})

    specs = {"sim/test/required": {"required": True, "default": 123.0}}
    mgr = make_manager(xp, specs)

    assert mgr.ready(0) is False

    for i in range(1, 50):
        mgr.ready(i)

    assert xp.isPluginEnabled(xp.getMyID()) == 1
    assert mgr.get_value("sim/test/required") == 0.0


# ===========================================================================
# 5. Unmanaged DataRef returns None
# ===========================================================================

def test_unmanaged_dataref_returns_none():
    xp = DummyXP()
    XPPython3.xp = xp

    mgr = make_manager(xp, specs=None)

    assert mgr.get_value("sim/unknown/path") is None


# ===========================================================================
# 6. Managed dummy returns default
# ===========================================================================

def test_dummy_returns_default():
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {"sim/test/default": {"required": False, "default": 7.7}}
    mgr = make_manager(xp, specs)

    assert mgr.get_value("sim/test/default") == 7.7


# ===========================================================================
# 7. Headless mode: all DataRefs managed even without specs
# ===========================================================================

def test_headless_auto_manage():
    xp = DummyXP()
    XPPython3.xp = xp

    mgr = make_manager(xp, specs=None)

    mgr.specs["sim/test/auto"] = DataRefSpec.dummy(
        "sim/test/auto",
        required=False,
        default=55.0,
    )

    assert mgr.get_value("sim/test/auto") == 55.0


# ===========================================================================
# 8. Real XP value read after promotion
# ===========================================================================

def test_real_value_after_promotion(monkeypatch):
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {"sim/test/live": {"required": False, "default": 1.0}}
    mgr = make_manager(xp, specs)

    monkeypatch.setattr(mgr, "_notify_dataref_changed", lambda *a, **k: None, raising=False)

    mgr.ready(0)
    mgr.ready(1)

    h = xp.findDataRef("sim/test/live")
    xp.setDataf(h, 88.8)

    assert mgr.get_value("sim/test/live") == 88.8


# ===========================================================================
# 9. set_value: scalar write
# ===========================================================================

def test_set_value_scalar():
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {"sim/test/scalar": {"required": False, "default": 0.0}}
    mgr = make_manager(xp, specs)

    mgr.ready(0)
    mgr.ready(1)

    mgr.set_value("sim/test/scalar", 12.5)
    assert mgr.get_value("sim/test/scalar") == 12.5


# ===========================================================================
# 10. set_value: float array write
# ===========================================================================

def test_set_value_array_float():
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {"sim/test/arr": {"required": False, "default": [0.0, 0.0, 0.0]}}
    mgr = make_manager(xp, specs)

    mgr.ready(0)
    mgr.ready(1)

    mgr.set_value("sim/test/arr", [1.1, 2.2, 3.3])
    assert mgr.get_value("sim/test/arr") == [1.1, 2.2, 3.3]


# ===========================================================================
# 11. set_value: wrong array size raises
# ===========================================================================

def test_set_value_wrong_size_raises():
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {"sim/test/arr": {"required": False, "default": [0.0, 0.0]}}
    mgr = make_manager(xp, specs)

    mgr.ready(0)
    mgr.ready(1)

    with pytest.raises(ValueError):
        mgr.set_value("sim/test/arr", [1.0, 2.0, 3.0])


# ===========================================================================
# 12. set_value: not writable raises
# ===========================================================================

def test_set_value_not_writable():
    xp = DummyXP()
    XPPython3.xp = xp

    # Create a dummy spec
    specs = {"sim/test/ro": {"required": False, "default": 5.0}}
    mgr = make_manager(xp, specs)

    # Promote it to a real DataRef
    mgr.ready(0)
    mgr.ready(1)

    # Now mark it non-writable AFTER promotion
    spec = mgr.specs["sim/test/ro"]
    spec.writable = False

    with pytest.raises(PermissionError):
        mgr.set_value("sim/test/ro", 10.0)


# ===========================================================================
# 13. set_value: dummy spec cannot be written
# ===========================================================================

def test_set_value_on_dummy_raises():
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {"sim/test/dummy": {"required": False, "default": 9.9}}
    mgr = make_manager(xp, specs)

    with pytest.raises(RuntimeError):
        mgr.set_value("sim/test/dummy", 1.0)


# ===========================================================================
# 14. set_value: unmanaged DataRef raises
# ===========================================================================

def test_set_value_unmanaged_raises():
    xp = DummyXP()
    XPPython3.xp = xp

    mgr = make_manager(xp, specs=None)

    with pytest.raises(KeyError):
        mgr.set_value("sim/unknown/path", 123)


# ===========================================================================
# 15. set_value: real XP write after promotion
# ===========================================================================

def test_set_value_after_promotion(monkeypatch):
    xp = DummyXP()
    XPPython3.xp = xp

    specs = {"sim/test/livewrite": {"required": False, "default": 1.0}}
    mgr = make_manager(xp, specs)

    mgr.ready(0)
    mgr.ready(1)

    mgr.set_value("sim/test/livewrite", 77.7)
    assert mgr.get_value("sim/test/livewrite") == 77.7
