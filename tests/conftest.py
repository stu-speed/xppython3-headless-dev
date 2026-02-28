# tests/conftest.py
# ===========================================================================
# Global pytest fixtures for simless tests
#
# ROLE
#   • Ensure each test begins with a clean XPPython3.xp binding.
#   • Provide a deterministic inline plugin module factory for loader tests.
#
# INVARIANTS
#   • Never instantiate FakeXP here.
#   • Never import plugin modules here.
#   • Inline plugin modules must define PythonInterface explicitly.
# ===========================================================================

import pytest
import types
import XPPython3

from sshd_extensions.dataref_manager import DRefType



@pytest.fixture(autouse=True)
def reset_xp():
    """
    Ensure each test starts with a clean FakeXP binding.

    Tests are responsible for constructing FakeXP and assigning:
        XPPython3.xp = FakeXP(...)
    """
    XPPython3.xp = None


@pytest.fixture
def inline_plugin():
    """
    Factory for creating inline plugin modules.

    Usage:
        mod = inline_plugin(
            name="my_plugin",
            plugin_obj=plugin_instance
        )

    The returned object is a ModuleType suitable for SimlessPluginLoader.
    """

    def _create(
        *,
        name: str,
        plugin_obj,
    ):
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

@pytest.fixture
def update_dataref():
    """
    Test-only helper that coerces dummy FakeDataRef fields without promoting.
    Mirrors the semantics expected by test_update_dummy_ref_validation.
    """
    def _update(ref, *, dtype: DRefType, size=None, value=None):
        # Must be dummy
        if not ref.is_dummy:
            raise RuntimeError("update_dataref only valid for dummy refs")

        # Validate size
        if size is not None and size <= 0:
            raise ValueError("size must be > 0")

        # Apply coercions
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

