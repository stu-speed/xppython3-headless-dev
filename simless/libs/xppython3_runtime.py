from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any


def wire_xppython3_runtime(xp: Any) -> None:
    """
    Install a FakeXP-backed runtime façade for the XPPython3 API.

    This preserves the real XPPython3 package (including xp_typing, utils, etc.)
    and replaces only the `xp` submodule with a dynamic façade whose attributes
    forward to the provided FakeXP instance.

    After wiring:

      • import xp
      • from XPPython3 import xp
      • from XPPython3.xp import foo

    all resolve to a lightweight proxy module whose attribute access is
    delegated to the FakeXP object.  All other XPPython3 submodules remain
    importable and unchanged.
    """

    project_root = Path(__file__).resolve().parents[2]
    stubs_root = project_root / "stubs"
    stubs_pkg_path = stubs_root / "XPPython3"

    # ⭐ Use the real XPPython3 package — do NOT replace it
    import XPPython3
    xpp_pkg = XPPython3

    # xp façade module
    xp_mod = types.ModuleType("xp")
    xp_mod.VERSION = getattr(xp, "VERSION", "FakeXP")

    # ⭐ Forward attribute access to FakeXP
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
