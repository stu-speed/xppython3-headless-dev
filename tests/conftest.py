# tests/conftest.py

import pytest
import sys
import inspect
import simless.libs.loader as loader
import XPPython3


@pytest.fixture(autouse=True)
def reset_xp():
    # Ensure each test starts with a clean FakeXP binding
    XPPython3.xp = None


@pytest.fixture(autouse=True)
def bypass_plugin_loader(monkeypatch):
    """
    Forces SimlessPluginLoader to load inline plugins from sys.modules
    instead of requiring real files in plugins/.
    """

    # 1. Disable filesystem validation
    monkeypatch.setattr(
        loader.SimlessPluginLoader,
        "_validate",
        lambda self, name: True
    )

    # 2. Override _load_single to load inline modules from sys.modules
    def _load_single_inline(self, full_name: str):
        # full_name is "plugins.<name>"
        short_name = full_name.split(".", 1)[1]

        if short_name not in sys.modules:
            raise RuntimeError(
                f"[Loader] Inline plugin '{short_name}' not found in sys.modules"
            )

        module = sys.modules[short_name]

        iface_cls = getattr(module, "PythonInterface", None)
        if iface_cls is None or not inspect.isclass(iface_cls):
            raise RuntimeError(
                f"[Loader] Inline plugin '{short_name}' has no PythonInterface class"
            )

        # Instantiate PythonInterface
        iface = iface_cls()

        # Call XPluginStart() and normalize return tuple
        name, sig, desc = iface.XPluginStart()

        # Assign plugin_id using the loader’s per-instance counter
        plugin_id = self._next_id
        self._next_id += 1

        # Construct LoadedPlugin using the NEW signature
        return loader.LoadedPlugin(
            plugin_id=plugin_id,
            name=name,
            sig=sig,
            desc=desc,
            module=module,
            instance=iface,
        )

    monkeypatch.setattr(
        loader.SimlessPluginLoader,
        "_load_single",
        _load_single_inline
    )
