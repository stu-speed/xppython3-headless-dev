# tests/conftest.py
# ===========================================================================
# Global pytest fixtures for simless tests
#
# ROLE
#   • Ensure each test begins with a clean XPPython3.xp binding.
#   • Provide a deterministic inline plugin module factory for loader tests.
#   • Install the synthetic XPPython3 runtime early so production modules
#     (e.g., bridge_protocol) can import safely.
#
# INVARIANTS
#   • Never instantiate FakeXP for normal tests.
#   • Never import plugin modules here.
#   • Inline plugin modules must define PythonInterface explicitly.
# ===========================================================================

import types

import dearpygui.dearpygui as dpg
import pytest

import XPPython3
from PythonPlugins.sshd_extensions.dataref_manager import DRefType
from simless.libs.fake_xp import FakeXP
from simless.libs.xppython3_runtime import wire_xppython3_runtime

# This must run at import time, not inside a fixture
wire_xppython3_runtime(FakeXP(debug=False, enable_gui=False))


# ---------------------------------------------------------------------------
# Reset xp binding per test
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_xp():
    """
    Ensure each test starts with a clean XPPython3.xp binding.

    Tests that need FakeXP must explicitly assign:
        XPPython3.xp = FakeXP(...)
    """
    XPPython3.xp = None


# ---------------------------------------------------------------------------
# Ensure DPG teardown between tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def teardown_dpg():
    yield
    try:
        dpg.destroy_context()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Inline plugin factory
# ---------------------------------------------------------------------------
@pytest.fixture
def inline_plugin():
    def _create(*, name: str, plugin_obj):
        mod = types.ModuleType(name)

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

        mod.PythonInterface = PythonInterface
        return mod

    return _create


# ---------------------------------------------------------------------------
# Dummy DataRef coercion helper
# ---------------------------------------------------------------------------
@pytest.fixture
def update_dataref():
    def _update(ref, *, dtype: DRefType, size=None, value=None):
        if not ref.is_dummy:
            raise RuntimeError("update_dataref only valid for dummy refs")

        if size is not None and size <= 0:
            raise ValueError("size must be > 0")

        if dtype is not None:
            ref.type = dtype
            ref.type_known = True

        if size is not None:
            ref.size = size
            ref.is_array = size > 1
            ref.shape_known = True

        if value is not None:
            ref.value = value

        return True

    return _update
