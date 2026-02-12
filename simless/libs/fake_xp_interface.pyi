# simless/libs/fake_xp_interface.pyi
# ===========================================================================
# FakeXPInterface — simless-only extensions to SimlessXPInterface
#
# FakeXP implements:
#   • All methods of SimlessXPInterface (the production-safe xp.* API surface)
#   • Additional simless-only helpers for DataRef auto-registration,
#     DataRefManager binding, and simless lifecycle control.
#
# This interface is used ONLY for:
#   • simless development
#   • FakeXP implementation
#   • DataRefManager integration
#   • simless runner and test harnesses
#
# Production plugins MUST NOT import this file.
# ===========================================================================

from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

# Base production-safe xp.* API surface
from simless.libs.simless_xp_interface import SimlessXPInterface

# Simless-only DataRef types
from simless.libs.fake_xp_dataref import FakeDataRef


# ===========================================================================
# FakeXPInterface Protocol
# ===========================================================================
@runtime_checkable
class FakeXPInterface(SimlessXPInterface, Protocol):
    """
    Simless-only API surface implemented by FakeXP.

    These methods do NOT exist in real XPPython3 and must never appear in
    SimlessXPInterface. They are used only by the simless runner,
    DataRefManager, bridge modules, and test harnesses.
    """

    # ------------------------------------------------------------------
    # Simless configuration flags
    # ------------------------------------------------------------------
    enable_gui: bool
    debug: bool

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

    # ------------------------------------------------------------------
    # Simless lifecycle control (public simless API)
    # ------------------------------------------------------------------
    def run_plugin_lifecycle(
        self,
        plugin_names: list[str],
        *,
        run_time: float = -1.0,
    ) -> None:
        """
        Public simless entry point for executing plugin lifecycles.

        Used by:
          • simless runner scripts
          • GUI harnesses
          • automated plugin tests
          • CI systems

        Delegates to the internal SimlessRunner.
        """
        ...

    # ------------------------------------------------------------------
    # Internal lifecycle teardown (private)
    # ------------------------------------------------------------------
    def _quit(self) -> None:
        """
        Stop the internal runner.

        Internal use only. Not part of the public simless API.
        """
        ...

    # ------------------------------------------------------------------
    # Internal debug helper (private)
    # ------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        """
        Internal debug logging helper.
        """
        ...
