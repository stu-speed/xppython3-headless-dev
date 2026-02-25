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
from typing import Any, Protocol, runtime_checkable, Optional, List

from simless.libs.simless_xp_interface import SimlessXPInterface
from simless.libs.fake_xp_dataref_types import FakeDataRef
from sshd_extensions.bridge_protocol import XPBridgeClient
from simless.libs.runner import SimlessRunner
from simless.libs.fake_xp_widget import XPWidgetID
from sshd_extensions.dataref_manager import DataRefManager


@runtime_checkable
class FakeXPInterface(SimlessXPInterface, Protocol):
    """
    Simless-only API surface implemented by FakeXP.

    FakeXP extends the production-safe SimlessXPInterface with:
      • DataRef auto-registration helpers
      • DataRefManager binding
      • simless lifecycle control
      • bridge client creation and management
      • GUI + widget + flightloop subsystems
    """

    # ------------------------------------------------------------------
    # Simless configuration flags
    # ------------------------------------------------------------------
    enable_gui: bool
    debug: bool

    # ------------------------------------------------------------------
    # Core simless state (strong typing)
    # ------------------------------------------------------------------
    _sim_time: float
    _keyboard_focus: XPWidgetID | None

    # Runner
    _simless_runner: SimlessRunner

    # ------------------------------------------------------------------
    # DataRefManager binding (simless only)
    # ------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: Any) -> None:
        """
        Attach the DataRefManager so FakeXP can honor plugin defaults.
        Real XPPython3 does not support this.
        """
        ...

    # ----------------------------------------------------------------------
    # DPG INITIALIZATION (PRODUCTION-PARITY)
    # ----------------------------------------------------------------------
    def init_graphics_root(self) -> None:
        """
        Initialize DearPyGui context, viewport, and root graphics surface
        BEFORE any plugin enable. This matches production X-Plane behavior:
        the widget system is fully ready before plugins run.

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
    # Internal debug helper (private)
    # ------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        """
        Internal debug logging helper.
        """
        ...
