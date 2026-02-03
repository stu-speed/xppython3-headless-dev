# ===========================================================================
# fake_xp_loader.py — INTERNAL FakeXP plugin loader
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
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


@dataclass
class LoadedPlugin:
    name: str
    sig: str
    desc: str
    module: ModuleType
    instance: Any


class FakeXPPluginLoader:
    """Internal loader used only by FakeXPRunner."""

    def __init__(self, xp: Any) -> None:
        self.root = Path(__file__).resolve().parents[2] / "plugins"
        self.xp = xp

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_sys_path(self) -> None:
        root_str = str(self.root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            self.xp.log(f"[Loader] Added to sys.path: {root_str}")

    def _validate(self, name: str) -> None:
        """Ensure plugins/<name>.py exists, else raise."""
        if not (self.root / f"{name}.py").exists():
            raise RuntimeError(f"[Loader] Plugin '{name}' not found in plugins/")

    # ------------------------------------------------------------------
    # Public API (internal to runner)
    # ------------------------------------------------------------------

    def load_plugins(self, module_names: list[str]) -> list[LoadedPlugin]:
        """Load and instantiate plugins. Hard‑fail on ANY error."""
        self._ensure_sys_path()

        plugins: list[LoadedPlugin] = []

        for name in module_names:
            self._validate(name)
            full_name = f"plugins.{name}"
            plugin = self._load_single(full_name)
            plugins.append(plugin)

        return plugins

    # ------------------------------------------------------------------
    # Single plugin load
    # ------------------------------------------------------------------

    def _load_single(self, full_name: str) -> LoadedPlugin:
        self.xp.log(f"[Loader] Loading module {full_name}")

        try:
            module = importlib.import_module(full_name)
        except Exception as exc:
            raise RuntimeError(f"[Loader] Import failed for {full_name}: {exc!r}")

        iface_cls = getattr(module, "PythonInterface", None)
        if iface_cls is None or not inspect.isclass(iface_cls):
            raise RuntimeError(f"[Loader] {full_name} has no PythonInterface class")

        try:
            instance = iface_cls()
        except Exception as exc:
            raise RuntimeError(f"[Loader] Failed to instantiate PythonInterface: {exc!r}")

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
