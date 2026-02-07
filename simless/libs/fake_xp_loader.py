# ===========================================================================
# fake_xp_loader.py — INTERNAL FakeXP plugin loader (fully typed)
#
# Not exposed to user code. Used exclusively by FakeXPRunner.
#
# Responsibilities:
#   • Load PI_*.py modules from ./plugins/
#   • Instantiate PythonInterface
#   • Call XPluginStart() to retrieve (Name, Sig, Desc)
#   • Hard‑fail (raise RuntimeError) on ANY error
# ===========================================================================

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, TypedDict, TYPE_CHECKING, List

if TYPE_CHECKING:
    from simless.libs.fake_xp.fakexp import FakeXP


# ---------------------------------------------------------------------------
# PythonInterface Protocol (production‑authentic)
# ---------------------------------------------------------------------------

class PythonInterfaceProto(Protocol):
    """
    Structural type for plugin PythonInterface classes.
    FakeXP never imports plugin internals, so we use a Protocol.
    """

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
    """
    _next_id: int = 1

    def __init__(
        self,
        name: str,
        sig: str,
        desc: str,
        module: ModuleType,
        instance: PythonInterfaceProto,
    ) -> None:
        self.name: str = name
        self.signature: str = sig
        self.description: str = desc

        self.module: ModuleType = module
        self.instance: PythonInterfaceProto = instance

        self.plugin_id: int = LoadedPlugin._next_id
        LoadedPlugin._next_id += 1

    def __repr__(self) -> str:
        return f"<LoadedPlugin id={self.plugin_id} name={self.name}>"


# ---------------------------------------------------------------------------
# FakeXPPluginLoader — internal loader used only by FakeXPRunner
# ---------------------------------------------------------------------------

class FakeXPPluginLoader:
    def __init__(self, xp: FakeXP) -> None:
        # Project root → plugins/
        self.root: Path = Path(__file__).resolve().parents[2] / "plugins"
        self.xp: FakeXP = xp

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    def _ensure_sys_path(self) -> None:
        """
        Ensure plugins/ is on sys.path so imports like:
            import PI_sshd_OTA
            import sshd_extensions.datarefs
        resolve exactly like X‑Plane.
        """
        root_str = str(self.root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            self.xp.log(f"[Loader] Added to sys.path: {root_str}")

    def _validate(self, name: str) -> None:
        """Ensure plugins/<name>.py exists, else raise."""
        if not (self.root / f"{name}.py").exists():
            raise RuntimeError(f"[Loader] Plugin '{name}' not found in plugins/")

    # ----------------------------------------------------------------------
    # Public API (internal to runner)
    # ----------------------------------------------------------------------

    def load_plugins(self, module_names: List[str]) -> List[LoadedPlugin]:
        """Load and instantiate plugins. Hard‑fail on ANY error."""
        self._ensure_sys_path()

        plugins: List[LoadedPlugin] = []

        for name in module_names:
            self._validate(name)
            full_name = f"plugins.{name}"
            plugin = self._load_single(full_name)
            plugins.append(plugin)

        return plugins

    # ----------------------------------------------------------------------
    # Single plugin load
    # ----------------------------------------------------------------------

    def _load_single(self, full_name: str) -> LoadedPlugin:
        """
        Import module, instantiate PythonInterface, call XPluginStart.
        """
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

        return LoadedPlugin(
            name=name,
            sig=sig,
            desc=desc,
            module=module,
            instance=instance,
        )
