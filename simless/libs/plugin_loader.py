from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


# ---------------------------------------------------------------------------
# Plugin interface protocol (X‑Plane authentic)
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
    """
    Loads Python plugins from plugins/PythonPlugins, wires a synthetic
    XPPython3 runtime, and exposes X‑Plane‑authentic plugin lifecycle behavior.
    """

    def __init__(self, xp: FakeXP) -> None:
        project_root = Path(__file__).resolve().parents[2]

        # Real X‑Plane structure:
        self.plugins_root = project_root / "plugins"
        self.root = self.plugins_root / "PythonPlugins"
        self.xppython3_root = self.plugins_root / "XPPython3"

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
        Ensure sys.path contains all XPPython3‑authentic roots:

          • plugins/                     → supports `import xp`
          • plugins/PythonPlugins/       → plugin modules
          • plugins/XPPython3/           → synthetic XPPython3 runtime
        """
        for path in (self.plugins_root, self.root, self.xppython3_root):
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

          • from XPPython3 import xp
          • import XPPython3.xp
          • import xp

        xp.* is a façade over FakeXP.
        """
        import types

        # ------------------------------------------------------------
        # 1. Create synthetic XPPython3 package
        # ------------------------------------------------------------
        xpp_pkg = types.ModuleType("XPPython3")
        xpp_pkg.__path__ = [str(self.xppython3_root)]
        xpp_pkg.__package__ = "XPPython3"
        sys.modules["XPPython3"] = xpp_pkg

        # ------------------------------------------------------------
        # 2. Create xp façade module
        # ------------------------------------------------------------
        xp_mod = types.ModuleType("xp")
        backend = self.xp

        # Optional: keep reference
        xp_mod.xp = backend

        # Provide VERSION for plugin logging
        xp_mod.VERSION = getattr(backend, "VERSION", "FakeXP")

        # Expose ALL public FakeXP methods/attributes as xp.*
        for name in dir(backend):
            if not name.startswith("_"):
                setattr(xp_mod, name, getattr(backend, name))

        # ------------------------------------------------------------
        # 3. Register xp in all expected import locations
        # ------------------------------------------------------------
        sys.modules["xp"] = xp_mod
        sys.modules["XPPython3.xp"] = xp_mod

        # Allow: from XPPython3 import xp
        setattr(xpp_pkg, "xp", xp_mod)

        self.xp.log("[Loader] Synthetic XPPython3 runtime wired (supports import xp, XPPython3.xp)")

    # ----------------------------------------------------------------------
    # Plugin lookup APIs
    # ----------------------------------------------------------------------

    def get_plugin(self, plugin_id: int) -> LoadedPlugin | None:
        return next((p for p in self._loaded_plugins if p.plugin_id == plugin_id), None)

    def find_plugin_by_signature(self, signature: str) -> int:
        return next((p.plugin_id for p in self._loaded_plugins if p.signature == signature), -1)

    def find_plugin_by_path(self, path: str) -> int:
        return next(
            (p.plugin_id for p in self._loaded_plugins if getattr(p.module, "__file__", None) == path),
            -1,
        )

    # ----------------------------------------------------------------------
    # Plugin loading
    # ----------------------------------------------------------------------

    def _validate(self, name: str) -> None:
        plugin_path = self.root / f"{name}.py"
        if not plugin_path.exists():
            raise RuntimeError(f"[Loader] Plugin '{name}' not found in {self.root}")

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

        # Provide xp.* façade to plugin instance
        instance.xp = self.xp

        # Run XPluginStart
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
