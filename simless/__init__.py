# simless/__init__.pyi  —  Simless‑only stub
# ===========================================================================
# PURPOSE
#   This file provides IDE and type‑checker visibility for the dynamically
#   injected `xp` object used by FakeXP during simless execution.
#
# WHY THIS FILE EXISTS
#   - The real XPPython3 package does NOT define `xp` statically.
#   - In production, `xp` is created at runtime by the XPPython3 plugin loader.
#   - In simless mode, FakeXP assigns `XPPython3.xp = self` during startup.
#   - PyCharm and mypy cannot see runtime‑injected attributes unless a stub
#     declares them.
#
# CRITICAL CONSTRAINT
#   This stub MUST NOT be placed inside the real XPPython3 installation.
#   Production plugins import `from XPPython3 import xp`, and they must NOT see
#   simless‑only types or interfaces.
#
#   Instead, this file lives in a simless‑only stub directory (e.g.,
#   simless_stubs/XPPython3/) which is added to the IDE/mypy search path.
#
# CONTRACT
#   - Declares that `xp` exists.
#   - Declares that `xp` implements the XPInterface Protocol.
#   - Does NOT modify runtime behavior.
#   - Does NOT rebind or instantiate xp.
#   - Exists solely for static analysis and editor support.
# ===========================================================================

from .libs.fake_xp_interface import FakeXPInterface

# xp is dynamically assigned at runtime by FakeXP (simless) or the real
# XPPython3 loader (production). This declaration is for static typing only.
xp: FakeXPInterface
