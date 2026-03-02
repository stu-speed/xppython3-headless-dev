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

from simless.libs.fake_xp_types import FakeDataRef
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
    # DPG GRAPHICS
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

    def dpg_delete_item(self, dpg_id: int) -> None: ...

    def dpg_add_window(
        self,
        label: Optional[str] = None,
        user_data: Any = None,
        use_internal_label: bool = True,
        tag: int | str = 0,
        width: int = 0,
        height: int = 0,
        indent: int = -1,
        show: bool = True,
        pos: Optional[list[int]] = None,
        delay_search: bool = False,
        min_size: Optional[list[int]] = None,
        max_size: Optional[list[int]] = None,
        menubar: bool = False,
        collapsed: bool = False,
        autosize: bool = False,
        no_resize: bool = False,
        no_title_bar: bool = False,
        no_move: bool = False,
        no_scrollbar: bool = False,
        no_collapse: bool = False,
        horizontal_scrollbar: bool = False,
        no_focus_on_appearing: bool = False,
        no_bring_to_front_on_focus: bool = False,
        no_close: bool = False,
        no_background: bool = False,
        modal: bool = False,
        popup: bool = False,
        no_saved_settings: bool = False,
        no_open_over_existing_popup: bool = True,
        no_scroll_with_mouse: bool = False,
        on_close: Optional[Callable[[], Any]] = None,
        **kwargs: Any,
    ) -> int | str: ...

    def dpg_add_child_window(
        self,
        label: str | None = None,
        user_data: Any | None = None,
        use_internal_label: bool = True,
        tag: int | str = 0,
        width: int = 0,
        height: int = 0,
        indent: int = -1,
        parent: int | str = 0,
        before: int | str = 0,
        payload_type: str = "$$DPG_PAYLOAD",
        drop_callback: Callable[[Any, Any, Any], Any] | None = None,
        show: bool = True,
        pos: list[int] | None = None,
        filter_key: str = "",
        delay_search: bool = False,
        tracked: bool = False,
        track_offset: float = 0.5,
        border: bool = True,
        autosize_x: bool = False,
        autosize_y: bool = False,
        no_scrollbar: bool = False,
        horizontal_scrollbar: bool = False,
        menubar: bool = False,
        no_scroll_with_mouse: bool = False,
        flattened_navigation: bool = True,
        **kwargs: Any,
    ) -> int | str: ...

    def dpg_add_text(
        self,
        default_value: str = "",
        label: str | None = None,
        user_data: Any | None = None,
        use_internal_label: bool = True,
        tag: int | str = 0,
        indent: int = -1,
        parent: int | str = 0,
        before: int | str = 0,
        source: int | str = 0,
        payload_type: str = "$$DPG_PAYLOAD",
        drag_callback: Callable[[Any, Any], Any] | None = None,
        drop_callback: Callable[[Any, Any], Any] | None = None,
        show: bool = True,
        pos: list[int] | None = None,
        filter_key: str = "",
        tracked: bool = False,
        track_offset: float = 0.5,
        wrap: int = -1,
        bullet: bool = False,
        color: list[int] | None = None,
        show_label: bool = False,
        **kwargs: Any,
    ) -> int | str: ...

    def dpg_add_input_text(
        self,
        label: str | None = None,
        user_data: Any | None = None,
        use_internal_label: bool = True,
        tag: int | str = 0,
        width: int = 0,
        height: int = 0,
        indent: int = -1,
        parent: int | str = 0,
        before: int | str = 0,
        source: int | str = 0,
        payload_type: str = "$$DPG_PAYLOAD",
        callback: Callable[[Any, Any, Any], Any] | None = None,
        drag_callback: Callable[[Any, Any, Any], Any] | None = None,
        drop_callback: Callable[[Any, Any, Any], Any] | None = None,
        show: bool = True,
        enabled: bool = True,
        pos: list[int] | None = None,
        filter_key: str = "",
        tracked: bool = False,
        track_offset: float = 0.5,
        default_value: str = "",
        hint: str = "",
        multiline: bool = False,
        no_spaces: bool = False,
        uppercase: bool = False,
        tab_input: bool = False,
        decimal: bool = False,
        hexadecimal: bool = False,
        readonly: bool = False,
        password: bool = False,
        scientific: bool = False,
        on_enter: bool = False,
        **kwargs: Any,
    ) -> int | str: ...

    def dpg_add_slider_int(
        self,
        label: str | None = None,
        user_data: Any | None = None,
        use_internal_label: bool = True,
        tag: int | str = 0,
        width: int = 0,
        height: int = 0,
        indent: int = -1,
        parent: int | str = 0,
        before: int | str = 0,
        source: int | str = 0,
        payload_type: str = "$$DPG_PAYLOAD",
        callback: Callable[[Any, Any, Any], Any] | None = None,
        drag_callback: Callable[[Any, Any, Any], Any] | None = None,
        drop_callback: Callable[[Any, Any, Any], Any] | None = None,
        show: bool = True,
        enabled: bool = True,
        pos: list[int] | None = None,
        filter_key: str = "",
        tracked: bool = False,
        track_offset: float = 0.5,
        default_value: int = 0,
        vertical: bool = False,
        no_input: bool = False,
        clamped: bool = False,
        min_value: int = 0,
        max_value: int = 100,
        format: str = "%d",
        **kwargs: Any,
    ) -> int | str: ...

    def dpg_add_button(
        self,
        label: str | None = None,
        user_data: Any | None = None,
        use_internal_label: bool = True,
        tag: int | str = 0,
        width: int = 0,
        height: int = 0,
        indent: int = -1,
        parent: int | str = 0,
        before: int | str = 0,
        payload_type: str = "$$DPG_PAYLOAD",
        callback: Callable[[Any, Any, Any], Any] | None = None,
        drag_callback: Callable[[Any, Any, Any], Any] | None = None,
        drop_callback: Callable[[Any, Any, Any], Any] | None = None,
        show: bool = True,
        enabled: bool = True,
        pos: list[int] | None = None,
        filter_key: str = "",
        tracked: bool = False,
        track_offset: float = 0.5,
        small: bool = False,
        arrow: bool = False,
        direction: int = 0,
        **kwargs: Any,
    ) -> int | str: ...

    def dpg_configure_item(
        self,
        item: int | str,
        **kwargs: Any,
    ) -> None: ...

    def dpg_show_item(
        self,
        item: int | str,
    ) -> None: ...

    def dpg_hide_item(
        self,
        item: int | str,
    ) -> None: ...

    def dpg_is_item_shown(
        self,
        item: int | str,
    ) -> None: ...

    def dpg_set_value(
        self,
        item: int | str,
        value: Any,
        **kwargs: Any,
    ) -> None: ...

    def dpg_get_screen_size(self) -> tuple[int, int]: ...

    def dpg_get_mouse_pos(
        self,
        local: bool = True,
        **kwargs: Any,
    ) -> list[int] | tuple[int, ...]: ...


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

