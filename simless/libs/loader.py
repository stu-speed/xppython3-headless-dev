# ===========================================================================
# loader.py — INTERNAL FakeXP plugin loader (fully typed)
#
# ROLE
#   Instantiate plugin modules deterministically, bind required subsystems
#   (FakeXP, DataRefManager, runner), and expose a clean, explicit lifecycle
#   interface. The loader must remain minimal, predictable, and free of
#   hidden behavior or inference.
#
# CORE INVARIANTS
#   - Will use the Public API as much as possible
#   - Loader must not mutate plugin classes beyond documented fields.
#   - Loader must not infer plugin behavior; it only instantiates and binds.
# ===========================================================================

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol, List

from simless.libs.fake_xp_interface import FakeXPInterface


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
        self.enabled = False

    def __repr__(self) -> str:
        return f"<LoadedPlugin id={self.plugin_id} name={self.name}>"


# ---------------------------------------------------------------------------
# SimlessPluginLoader — internal loader used only by FakeXPRunner
# ---------------------------------------------------------------------------

class SimlessPluginLoader:
    def __init__(self, xp: FakeXPInterface) -> None:
        # Project root → plugins/
        self.root: Path = Path(__file__).resolve().parents[2] / "plugins"
        self.xp = xp

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

    def load_plugins(self, modules: List[str | ModuleType]) -> List[LoadedPlugin]:
        """
        Load plugins given either:
          • string module names (e.g. "my_plugin")
          • inline module objects (already imported)
        """
        self._ensure_sys_path()

        plugins: List[LoadedPlugin] = []

        for item in modules:
            if isinstance(item, str):
                # Normal plugin name
                self._validate(item)
                full_name = f"plugins.{item}"
                plugin = self._load_single(full_name)

            elif isinstance(item, ModuleType):
                # Inline plugin module
                plugin = self._load_inline(item)

            else:
                raise TypeError(f"[Loader] Unsupported plugin spec: {item!r}")

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
    # Single plugin load (string‑based)
    # ----------------------------------------------------------------------

    def _load_single(self, full_name: str) -> LoadedPlugin:
        self.xp.log(f"[Loader] Loading module {full_name}")

        try:
            module: ModuleType = importlib.import_module(full_name)
        except Exception as exc:
            raise RuntimeError(f"[Loader] Import failed for {full_name}: {exc!r}")

        return self._load_inline(module)

    # ----------------------------------------------------------------------
    # Inline plugin load (ModuleType‑based)
    # ----------------------------------------------------------------------

    def _load_inline(self, module: ModuleType) -> LoadedPlugin:
        """
        Load a plugin from an already-imported module.
        Used for simless inline plugin tests.
        """
        self.xp.log(f"[Loader] Loading inline module {module.__name__}")

        iface_cls = getattr(module, "PythonInterface", None)
        if iface_cls is None or not inspect.isclass(iface_cls):
            raise RuntimeError(f"[Loader] Inline module {module.__name__} has no PythonInterface class")

        try:
            instance: PythonInterfaceProto = iface_cls()
        except Exception as exc:
            raise RuntimeError(f"[Loader] Failed to instantiate inline PythonInterface: {exc!r}")

        self.xp.log("[Loader] === XPluginStart BEGIN ===")
        instance.xp = self.xp
        try:
            self.xp.log(f"[Loader] → XPluginStart: {module.__name__}")
            name, sig, desc = instance.XPluginStart()
        except Exception as exc:
            raise RuntimeError(f"[Loader] XPluginStart failed for inline module {module.__name__}: {exc!r}")
        self.xp.log("[Runner] === XPluginStart END ===")

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
