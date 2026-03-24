from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Protocol

from simless.libs.fake_xp_interface import FakeXPInterface


# ---------------------------------------------------------------------------
# Plugin interface protocol
# ---------------------------------------------------------------------------

class PythonInterfaceProto(Protocol):
    def XPluginStart(self) -> tuple[str, str, str]: ...

    def XPluginEnable(self) -> int: ...

    def XPluginDisable(self) -> None: ...

    def XPluginStop(self) -> None: ...


# ---------------------------------------------------------------------------
# LoadedPlugin container
# ---------------------------------------------------------------------------

class LoadedPlugin:
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
# SimlessPluginLoader
# ---------------------------------------------------------------------------

class SimlessPluginLoader:
    def __init__(self, xp: FakeXPInterface) -> None:
        project_root = Path(__file__).resolve().parents[2]

        # plugins/ → PI_xxx, noaaweather, etc.
        self.root: Path = project_root / "plugins"

        # stubs/ → stubs/XPPython3/*
        self.stubs_root: Path = project_root / "stubs"

        self.xp = xp
        self._loaded_plugins: List[LoadedPlugin] = []
        self._next_id: int = 1

        self._ensure_sys_path()
        self._wire_xppython3_runtime()

    # ----------------------------------------------------------------------
    # sys.path setup
    # ----------------------------------------------------------------------

    def _ensure_sys_path(self) -> None:
        """
        Ensure:
          • plugins/ is on sys.path (PI_xxx, noaaweather)
          • stubs/ is on sys.path (so stubs/XPPython3 is visible)
        """
        for path in (self.root, self.stubs_root):
            s = str(path)
            if s not in sys.path:
                sys.path.insert(0, s)
                self.xp.log(f"[Loader] Added to sys.path: {s}")

    # ----------------------------------------------------------------------
    # Synthetic XPPython3 runtime
    # ----------------------------------------------------------------------

    def _wire_xppython3_runtime(self) -> None:
        """
        Provide a synthetic XPPython3 runtime environment:
          • xp.* is a full façade over FakeXP
          • XPPython3 is a namespace package pointing at stubs/XPPython3
          • No modules are pre-imported; plugins import them normally
          • xp.pyi remains the authoritative static type contract
        """
        import sys, types

        # Path to stubs/XPPython3
        stubs_pkg_path = self.stubs_root / "XPPython3"
        if not stubs_pkg_path.exists():
            self.xp.log(f"[Loader] No stubs/XPPython3 directory at {stubs_pkg_path}")
            return

        # ------------------------------------------------------------
        # 1. Create synthetic XPPython3 package (no __init__ executed)
        # ------------------------------------------------------------
        xpp_pkg = types.ModuleType("XPPython3")
        xpp_pkg.__path__ = [str(stubs_pkg_path)]
        sys.modules["XPPython3"] = xpp_pkg

        # ------------------------------------------------------------
        # 2. Create synthetic xp module: full façade over FakeXP
        # ------------------------------------------------------------
        xp_mod = types.ModuleType("xp")
        backend = self.xp  # FakeXP instance

        # Optional: keep reference
        xp_mod.xp = backend

        # Provide VERSION for plugin logging
        xp_mod.VERSION = getattr(backend, "VERSION", "FakeXP")

        # Expose ALL public FakeXP methods/attributes as xp.*
        for name in dir(backend):
            if name.startswith("_"):
                continue
            setattr(xp_mod, name, getattr(backend, name))

        # Register xp module
        sys.modules["xp"] = xp_mod
        sys.modules["XPPython3.xp"] = xp_mod

        self.xp.log("[Loader] Synthetic XPPython3 runtime wired (xp façade, no pre-imports)")

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
    # Plugin loading
    # ----------------------------------------------------------------------

    def _validate(self, name: str) -> None:
        if not (self.root / f"{name}.py").exists():
            raise RuntimeError(f"[Loader] Plugin '{name}' not found in plugins/")

    def load_plugins(self, modules: List[str | ModuleType]) -> List[LoadedPlugin]:
        plugins: List[LoadedPlugin] = []

        for item in modules:
            if isinstance(item, str):
                self._validate(item)
                plugin = self._load_single(item)
            elif isinstance(item, ModuleType):
                plugin = self._load_inline(item)
            else:
                raise TypeError(f"[Loader] Unsupported plugin spec: {item!r}")

            plugins.append(plugin)

        self._loaded_plugins = plugins
        return plugins

    def _load_single(self, name: str) -> LoadedPlugin:
        self.xp.log(f"[Loader] Loading module {name}")
        try:
            module: ModuleType = importlib.import_module(name)
        except Exception as exc:
            raise RuntimeError(f"[Loader] Import failed for {name}: {exc!r}")
        return self._load_inline(module)

    def _load_inline(self, module: ModuleType) -> LoadedPlugin:
        self.xp.log(f"[Loader] Loading inline module {module.__name__}")

        iface_cls = getattr(module, "PythonInterface", None)
        if iface_cls is None or not inspect.isclass(iface_cls):
            raise RuntimeError(f"[Loader] Inline module {module.__name__} has no PythonInterface class")

        try:
            instance: PythonInterfaceProto = iface_cls()
        except Exception as exc:
            raise RuntimeError(f"[Loader] Failed to instantiate PythonInterface: {exc!r}")

        instance.xp = self.xp

        self.xp.log("[Loader] === XPluginStart BEGIN ===")
        try:
            name, sig, desc = instance.XPluginStart()
        except Exception as exc:
            raise RuntimeError(f"[Loader] XPluginStart failed for {module.__name__}: {exc!r}")
        self.xp.log("[Loader] === XPluginStart END ===")

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
