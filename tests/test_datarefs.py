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

    # ------------------------------------------------------------------
    # Simulate REAL XP behavior:
    # Real XP returns None when a DataRef does not exist.
    #
    # So for this test, we disable FakeXP's fallback auto-generation
    # by overriding findDataRef to always return None.
    #
    # This forces DataRefManager to see "required DataRef never resolves".
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Simulate "no real XP" but DO NOT disable FakeXP auto-generation.
    #
    # Real XP would not provide this DataRef, but FakeXP *does* provide
    # auto-generated placeholders. Clearing _handles simulates "XP has
    # no explicit DataRefs", while still allowing FakeXP to auto-generate.
    # ------------------------------------------------------------------
    monkeypatch.setattr(xp, "_handles", {})

    specs = {"sim/test/required": {"required": True, "default": 123.0}}
    mgr = make_manager(xp, specs)

    assert mgr.ready(0) is False

    for i in range(1, 50):
        mgr.ready(i)

    # Plugin should NOT be disabled because FakeXP auto-generated the DataRef
    assert xp.isPluginEnabled(xp.getMyID()) == 1

    # Auto-generated dummy → promoted → default becomes 0.0
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

    # Avoid needing DataRefManager._notify_dataref_changed
    monkeypatch.setattr(mgr, "_notify_dataref_changed", lambda *a, **k: None, raising=False)

    mgr.ready(0)
    mgr.ready(1)

    h = xp.findDataRef("sim/test/live")
    xp.setDataf(h, 88.8)

    assert mgr.get_value("sim/test/live") == 88.8
