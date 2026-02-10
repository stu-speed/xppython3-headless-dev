# ===========================================================================
# loader.py — INTERNAL FakeXP plugin loader (fully typed)
#
# Not exposed to user code. Used exclusively by FakeXPRunner.
#
# Responsibilities:
#   • Load PI_*.py modules from ./plugins/
#   • Instantiate PythonInterface
#   • Call XPluginStart() to retrieve (Name, Sig, Desc)
#   • Maintain plugin registry for FakeXP (ID, signature, path)
#   • Hard‑fail (raise RuntimeError) on ANY error
# ===========================================================================

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol, TYPE_CHECKING, List

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


# ---------------------------------------------------------------------------
# PythonInterface Protocol (production‑authentic)
# ---------------------------------------------------------------------------

class PythonInterfaceProto(Protocol):
    def XPluginStart(self) -> tuple[str, str, str]:
        ...
    def XPluginEnable(self) -> int:
        ...
    def XPluginDisable(self) -> None:
        ...
    def XPluginStop(self) -> None:
        ...


# ---------------------------------------------------------------------------
# LoadedPlugin — strongly typed plugin wrapper
# ---------------------------------------------------------------------------

class LoadedPlugin:
    """
    Strongly‑typed wrapper around a PythonInterface‑based plugin.
    Plugin IDs are assigned by SimlessPluginLoader (per‑loader, not global).
    """

    def __init__(
        self,
        plugin_id: int,
        name: str,
        sig: str,
        desc: str,
        module: ModuleType,
        instance: PythonInterfaceProto,
    ) -> None:
        self.plugin_id = plugin_id
        self.name = name
        self.signature = sig
        self.description = desc
        self.module = module
        self.instance = instance

    def __repr__(self) -> str:
        return f"<LoadedPlugin id={self.plugin_id} name={self.name}>"


# ---------------------------------------------------------------------------
# SimlessPluginLoader — internal loader used only by FakeXPRunner
# ---------------------------------------------------------------------------

class SimlessPluginLoader:
    def __init__(self, xp: FakeXP) -> None:
        # Project root → plugins/
        self.root: Path = Path(__file__).resolve().parents[2] / "plugins"
        self.xp: FakeXP = xp

        # Registry of LoadedPlugin objects
        self._loaded_plugins: List[LoadedPlugin] = []

        # Per‑loader plugin ID counter (Pythonic, test‑safe)
        self._next_id: int = 1

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    def _ensure_sys_path(self) -> None:
        root_str = str(self.root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            self.xp.log(f"[Loader] Added to sys.path: {root_str}")

    def _validate(self, name: str) -> None:
        if not (self.root / f"{name}.py").exists():
            raise RuntimeError(f"[Loader] Plugin '{name}' not found in plugins/")

    # ----------------------------------------------------------------------
    # Public API (internal to runner)
    # ----------------------------------------------------------------------

    def load_plugins(self, module_names: List[str]) -> List[LoadedPlugin]:
        self._ensure_sys_path()

        plugins: List[LoadedPlugin] = []

        for name in module_names:
            self._validate(name)
            full_name = f"plugins.{name}"
            plugin = self._load_single(full_name)
            plugins.append(plugin)

        self._loaded_plugins = plugins
        return plugins

    # ----------------------------------------------------------------------
    # Plugin lookup APIs (X‑Plane authentic)
    # ----------------------------------------------------------------------

    def get_plugin(self, plugin_id: int) -> LoadedPlugin | None:
        for plugin in self._loaded_plugins:
            if plugin.plugin_id == plugin_id:
                return plugin
        return None

    def find_plugin_by_signature(self, signature: str) -> int:
        for plugin in self._loaded_plugins:
            if plugin.signature == signature:
                return plugin.plugin_id
        return -1

    def find_plugin_by_path(self, path: str) -> int:
        for plugin in self._loaded_plugins:
            module_path = getattr(plugin.module, "__file__", None)
            if module_path and module_path == path:
                return plugin.plugin_id
        return -1

    # ----------------------------------------------------------------------
    # Single plugin load
    # ----------------------------------------------------------------------

    def _load_single(self, full_name: str) -> LoadedPlugin:
        self.xp.log(f"[Loader] Loading module {full_name}")

        # Import module
        try:
            module: ModuleType = importlib.import_module(full_name)
        except Exception as exc:
            raise RuntimeError(f"[Loader] Import failed for {full_name}: {exc!r}")

        # Validate PythonInterface class
        iface_cls = getattr(module, "PythonInterface", None)
        if iface_cls is None or not inspect.isclass(iface_cls):
            raise RuntimeError(f"[Loader] {full_name} has no PythonInterface class")

        # Instantiate plugin
        try:
            instance: PythonInterfaceProto = iface_cls()
        except Exception as exc:
            raise RuntimeError(f"[Loader] Failed to instantiate PythonInterface: {exc!r}")

        # Call XPluginStart
        try:
            name, sig, desc = instance.XPluginStart()
        except Exception as exc:
            raise RuntimeError(f"[Loader] XPluginStart failed for {full_name}: {exc!r}")

        self.xp.log(f"[Loader] Loaded plugin {name} ({sig}) — {desc}")

        # Assign plugin ID (per‑loader, not global)
        plugin_id = self._next_id
        self._next_id += 1

        return LoadedPlugin(
            plugin_id=plugin_id,
            name=name,
            sig=sig,
            desc=desc,
            module=module,
            instance=instance,
        )
