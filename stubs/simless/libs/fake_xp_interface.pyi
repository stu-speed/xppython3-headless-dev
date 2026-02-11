# stubs/simless/libs/fake_xp_interface.pyi
# ===========================================================================
# FakeXPInterface — simless-only extensions to SimlessXPInterface
#
# FakeXP implements:
#   • All methods of SimlessXPInterface (the production-safe xp.* API surface)
#   • Additional simless-only helpers for DataRef auto-registration and
#     DataRefManager binding.
#
# Production plugins MUST NOT import this file. It is strictly for:
#   • simless development
#   • FakeXP implementation
#   • DataRefManager integration
#   • test harnesses
# ===========================================================================

from __future__ import annotations
from typing import Protocol, Any, runtime_checkable

# Simless base API surface (production-safe subset)
from simless.libs.simless_xp_interface import SimlessXPInterface

# Simless-only DataRef types
from simless.libs.fake_xp_dataref import FakeDataRef, DRefType


# ===========================================================================
# FakeXPInterface Protocol
# ===========================================================================
@runtime_checkable
class FakeXPInterface(SimlessXPInterface, Protocol):
    """
    Simless-only API surface implemented by FakeXP.

    These methods do NOT exist in real XPPython3 and must never appear in
    SimlessXPInterface. They are used only by the simless runner,
    DataRefManager, and test harnesses.
    """

    # ------------------------------------------------------------------
    # DataRef auto-registration (simless only)
    # ------------------------------------------------------------------
    def fake_register_dataref(
        self,
        path: str,
        *,
        xp_type: int,
        is_array: bool = False,
        size: int = 1,
        writable: bool = True,
    ) -> FakeDataRef:
        """
        Create a FakeDataRef entry and allocate default storage.
        Used by DataRefManager during simless initialization.
        """
        ...

    # ------------------------------------------------------------------
    # DataRefManager binding (simless only)
    # ------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: Any) -> None:
        """
        Attach the DataRefManager so FakeXP can honor plugin defaults.
        Real XPPython3 does not support this.
        """
        ...
