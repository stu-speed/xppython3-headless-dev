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
