from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any


def wire_xppython3_runtime(xp: Any) -> None:
    """
    Install a synthetic XPPython3 runtime:

      • import xp
      • from XPPython3 import xp
      • from XPPython3.xp import foo

    All resolve to a façade module whose attributes forward to FakeXP.
    """
    project_root = Path(__file__).resolve().parents[2]
    stubs_root = project_root / "stubs"
    stubs_pkg_path = stubs_root / "XPPython3"

    # Synthetic XPPython3 namespace package
    xpp_pkg = types.ModuleType("XPPython3")
    xpp_pkg.__path__ = [str(stubs_pkg_path)]
    xpp_pkg.__package__ = "XPPython3"
    sys.modules["XPPython3"] = xpp_pkg

    # xp façade module
    xp_mod = types.ModuleType("xp")
    xp_mod.VERSION = getattr(xp, "VERSION", "FakeXP")

    # ⭐ The magic: forward attribute access to FakeXP
    def __getattr__(name: str):
        return getattr(xp, name)

    def __dir__():
        return sorted(set(dir(xp)))

    xp_mod.__getattr__ = __getattr__
    xp_mod.__dir__ = __dir__

    # Register module
    sys.modules["xp"] = xp_mod
    sys.modules["XPPython3.xp"] = xp_mod
    setattr(xpp_pkg, "xp", xp_mod)
