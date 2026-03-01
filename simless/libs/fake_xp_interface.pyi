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

from typing import Any, Callable, Optional, Protocol, runtime_checkable

from simless.libs.fake_xp_dataref_types import FakeDataRef
from simless.libs.runner import SimlessRunner
from simless.libs.simless_xp_interface import SimlessXPInterface
from sshd_extensions.dataref_manager import DRefType
from XPPython3.xp_typing import (
    XPWidgetID
)


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
    _graphics_window: int | None

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

    def draw_frame(self) -> None: ...

    def all_widget_ids(self) -> list[XPWidgetID]: ...

    def map_widgets_to_dpg(self) -> None: ...

    def render_widget_frame(self) -> None: ...

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

    def quit_runner(self) -> None: ...

    # ------------------------------------------------------------------
    # Internal debug helper (private)
    # ------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        """
        Internal debug logging helper.
        """
        ...

    # ------------------------------------------------------------------
    # Dataref helpers
    # ------------------------------------------------------------------

    def update_dataref(
        self,
        ref: FakeDataRef,
        dtype: Optional[DRefType] = None,
        size: Optional[int] = None,
        writable: Optional[bool] = None,
        value: Optional[Any] = None,
    ) -> FakeDataRef: ...

    def add_handle(self, name: str, ref: FakeDataRef) -> None: ...

    def get_handle(self, name: str) -> Optional[FakeDataRef]: ...

    def del_handle(self, name) -> None: ...

    def all_handle_paths(self) -> list[str]: ...

    def all_handles(self) -> list[FakeDataRef]: ...

    def conform_dummy_to_value(
        self,
        ref: FakeDataRef,
        value,
        offset: int = 0,
        count: int | None = None,
    ) -> None: ...

    def promote_shape_from_value(
        self,
        ref: FakeDataRef,
        value: Any,
    ) -> None: ...

    def promote_type(
        self,
        ref: FakeDataRef,
        dtype: DRefType,
        writable: bool,
    ) -> None: ...

    def attach_handle_callback(self, cb: Optional[Callable[[FakeDataRef], None]]) -> None: ...

    def detach_handle_callback(self) -> None: ...

