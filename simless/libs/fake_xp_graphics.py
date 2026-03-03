# simless/libs/fake_xp_graphics.py
# ===========================================================================
# FakeXPGraphics — DearPyGui-backed graphics subsystem mixin for FakeXP
#
# ROLE
#   Provide a minimal, deterministic, XPLMGraphics-like façade for simless
#   execution. This subsystem mirrors the public xp.* graphics API surface
#   without inference, layout logic, or hidden state.
#
# CORE INVARIANTS
#   - Must match the production xp.* graphics API contract (xp.pyi).
#   - Must not infer semantics or perform validation.
#   - Must not mutate SDK-shaped objects.
#   - Must return deterministic values based solely on internal storage.
#
# LIFECYCLE INVARIANTS
#   - context_ready gates legality: any dpg.* call requires context_ready.
#   - layout_ready gates correctness: any geometry/layout-dependent operation
#     requires layout_ready (first DPG frame rendered).
#   - Violations raise immediately; nothing fails silently.
#
# SIMLESS RULES
#   - DearPyGui is used only for visualization; never exposed to plugins.
#   - DPG context + viewport + graphics surface are created BEFORE plugin enable.
#   - No automatic layout, no coordinate transforms.
#   - XP draw callbacks are driven by FakeXP, not DPG.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_graphics_api import FakeXPGraphicsAPI
from simless.libs.fake_xp_types import WindowExInfo, EventInfo, EventKind
from XPPython3.xp_typing import XPLMWindowID

DPGCallback = Callable[[int | str, Any, Any], Any]


class FakeXPGraphics(FakeXPGraphicsAPI):
    """DearPyGui-backed graphics subsystem mixin for FakeXP.

    This class owns the DearPyGui lifecycle and exposes:
      - An XPLMGraphics-like API surface (xp.* semantics)
      - A small, explicit set of graphics-owned DearPyGui helpers (dpg_*)

    The design is intentionally strict:
      - Any DPG call before context_ready raises.
      - Any geometry/layout-dependent operation before layout_ready raises.
      - No silent failure paths.
    """

    public_api_names = [
        # ------------------------------------------------------------------
        # XP Graphics API (XPLM-style semantics)
        # ------------------------------------------------------------------
        "registerDrawCallback",
        "unregisterDrawCallback",
        "getScreenSize",
        "getMouseLocation",
        "drawString",
        "drawNumber",
        "setGraphicsState",
        "bindTexture2d",
        "generateTextureNumbers",
        "deleteTexture",
        # ------------------------------------------------------------------
        # WindowEx API (graphics-owned windows)
        # ------------------------------------------------------------------
        "createWindowEx",
        "destroyWindow",
        "getWindowGeometry",
        "setWindowGeometry",
        "getWindowRefCon",
        "setWindowRefCon",
        "getWindowIsVisible",
        "setWindowIsVisible",
        "takeKeyboardFocus",
        "getScreenSize",
        "getMouseLocation",
        # ------------------------------------------------------------------
        # Raw DearPyGui helpers (graphics-owned, explicit)
        # ------------------------------------------------------------------
        "dpg_add_window",
        "dpg_add_child_window",
        "dpg_add_text",
        "dpg_add_input_text",
        "dpg_add_slider_int",
        "dpg_add_button",
        "dpg_configure_item",
        "dpg_set_value",
        "dpg_delete_item",
        "dpg_show_item",
        "dpg_hide_item",
        "dpg_is_item_shown",
        "dpg_is_dearpygui_running",
        "dpg_add_drawlist",
        "dpg_does_item_exist",
        "dpg_draw_text",
        "dpg_get_viewport_width",
        "dpg_get_viewport_height",
        # ------------------------------------------------------------------
        # Simless driver entry point (engine-owned)
        # ------------------------------------------------------------------
        "draw_frame",
    ]

    # ----------------------------------------------------------------------
    # INITIALIZATION
    # ----------------------------------------------------------------------
    def _init_graphics(self) -> None:
        """Initialize internal graphics state.

        Called by FakeXP during construction.

        This method sets up *graphics-layer* bookkeeping only.
        It does NOT create any widgets or windows and does NOT
        initialize DearPyGui itself.
        """
        self._draw_callbacks = []
        self._next_tex_id = 1
        self._textures = {}
        self._context_ready = False
        self._layout_ready = False
        self._screen_drawlist_back = None  # Behind all windows
        self._screen_drawlist_front = None  # Above all windows (optional)
        self._active_drawlist = None
        self._windows_ex: Dict[XPLMWindowID, WindowExInfo] = {}
        self._next_window_id = 1
        self._keyboard_focus_window = None

    # ----------------------------------------------------------------------
    # LIFECYCLE FLAGS
    # ----------------------------------------------------------------------
    @property
    def context_ready(self) -> bool:
        """Whether the DearPyGui context + viewport are initialized."""
        return self._context_ready

    @property
    def layout_ready(self) -> bool:
        """Whether at least one DPG frame has rendered (layout is valid)."""
        return self._layout_ready

    # ----------------------------------------------------------------------
    # DPG INITIALIZATION
    # ----------------------------------------------------------------------
    def init_graphics_root(self) -> None:
        """Initialize DearPyGui and create the global screen draw surfaces.

        This creates:
          - DPG context
          - DPG viewport
          - A viewport-attached drawlist representing the X-Plane screen

        Notes:
          - This must run before plugin enable (simless rule).
          - This surface is the target for drawString, drawLine, drawBox, etc.
          - WindowEx windows and widgets draw on top of this surface.
        """
        if self._context_ready:
            return

        dpg.create_context()
        dpg.create_viewport(
            title="Fake X-Plane",
            width=1920,
            height=1080,
        )
        dpg.setup_dearpygui()
        dpg.show_viewport()

        # ------------------------------------------------------------------
        # Global screen draw surfaces (XP graphics layer)
        # ------------------------------------------------------------------

        # Background screen surface (behind all windows)
        self._screen_drawlist_back = dpg.add_viewport_drawlist(front=False)

        # Foreground screen surface (above all windows, optional)
        self._screen_drawlist_front = dpg.add_viewport_drawlist(front=True)

        # Default target for XPLMGraphics calls
        self._active_drawlist = self._screen_drawlist_back

        self._context_ready = True
        self._layout_ready = False

    # ----------------------------------------------------------------------
    # FRAME RENDERING
    # ----------------------------------------------------------------------
    def draw_frame(self) -> None:
        """Render one simless frame.

        Ordering:
          1) If viewport closed, end run loop.
          2) Execute XP draw callbacks (screen-level).
          3) Render one DearPyGui frame (establish draw context).
          4) Execute WindowEx draw callbacks (window-local).
          5) On first rendered frame, set layout_ready and return.
          6) After layout_ready, render widget frame.
        """
        self._require_context()

        # If DPG window closed, end run loop
        if not dpg.is_dearpygui_running():
            self.xp.simless_runner.end_run_loop()
            return

        # --------------------------------------------------------------
        # 0) Clear draw surfaces (screen + windows) to avoid accumulation
        # --------------------------------------------------------------
        self._clear_drawlist_children(self._screen_drawlist_back)
        self._clear_drawlist_children(self._screen_drawlist_front)

        # --------------------------------------------------------------
        # 1) Global screen drawing (XPLMGraphics)
        #
        # Deterministic phase ordering:
        #   - For each phase: wantsBefore=1 callbacks first, then wantsBefore=0
        # --------------------------------------------------------------
        self._active_drawlist = self._screen_drawlist_back

        phases = sorted({phase for _, phase, _ in self._draw_callbacks})
        for phase in phases:
            for wants_before in (1, 0):
                for cb, cb_phase, cb_wants_before in list(self._draw_callbacks):
                    if cb_phase == phase and cb_wants_before == wants_before:
                        cb(phase, wants_before)

        # --------------------------------------------------------------
        # 2) Render one DearPyGui frame (establish draw context)
        # --------------------------------------------------------------
        dpg.render_dearpygui_frame()

        # --------------------------------------------------------------
        # 3) WindowEx drawing (graphics-owned windows)
        # --------------------------------------------------------------
        for info in self._iter_window_ex_in_layer_order():
            if not info.visible or info.draw_cb is None:
                continue

            self._clear_drawlist_children(info.drawlist_id)

            prev_drawlist = self._active_drawlist
            try:
                self._active_drawlist = info.drawlist_id
                info.draw_cb(info.wid, info.refcon)
            finally:
                self._active_drawlist = prev_drawlist

        # --------------------------------------------------------------
        # 4) First frame establishes layout
        # --------------------------------------------------------------
        if not self._layout_ready:
            self._layout_ready = True
            return

        # --------------------------------------------------------------
        # 5) Widget rendering (geometry-safe)
        # --------------------------------------------------------------
        self.xp.render_widget_frame()

    # ----------------------------------------------------------------------
    # DPG HELPERS (GRAPHICS-OWNED, FAIL-FAST)
    # ----------------------------------------------------------------------
    def dpg_is_dearpygui_running(self) -> bool:
        self._require_context()
        return dpg.is_dearpygui_running()

    def dpg_add_drawlist(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_drawlist(**kwargs)

    def dpg_does_item_exist(self, item: int | str) -> bool:
        self._require_context()
        return dpg.does_item_exist(item)

    def dpg_draw_text(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.draw_text(**kwargs)

    def dpg_get_viewport_width(self) -> int:
        self._require_context()
        self._require_layout()
        return dpg.get_viewport_width()

    def dpg_get_viewport_height(self) -> int:
        self._require_context()
        self._require_layout()
        return dpg.get_viewport_height()

    def dpg_delete_item(self, item: int | str) -> None:
        # Deletion during shutdown is legal and must be tolerant
        if not self._context_ready:
            return
        if not dpg.is_dearpygui_running():
            return
        dpg.delete_item(item)

    def dpg_add_window(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_window(**kwargs)

    def dpg_add_child_window(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_child_window(**kwargs)

    def dpg_add_text(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_text(**kwargs)

    def dpg_add_input_text(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_input_text(**kwargs)

    def dpg_add_slider_int(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_slider_int(**kwargs)

    def dpg_add_button(self, **kwargs: Any) -> int | str:
        self._require_context()
        return dpg.add_button(**kwargs)

    def dpg_configure_item(self, item: int | str, **kwargs: Any) -> None:
        self._require_context()
        dpg.configure_item(item, **kwargs)

    def dpg_set_value(self, item: int | str, value: Any, **kwargs: Any) -> None:
        self._require_context()
        dpg.set_value(item, value, **kwargs)

    def dpg_show_item(self, item: int | str) -> None:
        self._require_context()
        dpg.show_item(item)

    def dpg_hide_item(self, item: int | str) -> None:
        self._require_context()
        dpg.hide_item(item)

    def dpg_is_item_shown(self, item: int | str) -> bool:
        self._require_context()
        return dpg.is_item_shown(item)

    # ----------------------------------------------------------------------
    # INTERNAL HELPERS
    # ----------------------------------------------------------------------
    def _clear_drawlist_children(self, drawlist_id: Optional[int]) -> None:
        """Clear per-frame draw primitives to avoid unbounded accumulation."""
        if drawlist_id is None:
            return
        if not dpg.does_item_exist(drawlist_id):
            return
        dpg.delete_item(drawlist_id, children_only=True)

    def _iter_window_ex_in_layer_order(self):
        return sorted(
            self._windows_ex.values(),
            key=lambda w: w.layer,
        )

    def _install_dpg_input_callbacks(self) -> None:
        """Install DearPyGui input callbacks.

        This method is graphics-owned because it touches DPG directly.
        Callbacks must only enqueue EventInfo objects; XP semantics are
        applied later by FakeXPInput during the frame.
        """

        runner = self.xp.simless_runner

        # ------------------------------------------------------------
        # Mouse button down
        # ------------------------------------------------------------
        def on_mouse_down(sender, app_data, user_data):
            # app_data example: {"x": 412, "y": 233, "button": 0}
            runner.queue_input_event(
                EventInfo(
                    kind=EventKind.MOUSE_BUTTON,
                    x=int(app_data["x"]),
                    y=int(app_data["y"]),
                    state="down",
                    button=int(app_data.get("button", 0)),
                )
            )

        # ------------------------------------------------------------
        # Mouse button up
        # ------------------------------------------------------------
        def on_mouse_up(sender, app_data, user_data):
            runner.queue_input_event(
                EventInfo(
                    kind=EventKind.MOUSE_BUTTON,
                    x=int(app_data["x"]),
                    y=int(app_data["y"]),
                    state="up",
                    button=int(app_data.get("button", 0)),
                )
            )

        # ------------------------------------------------------------
        # Mouse movement (cursor queries)
        # ------------------------------------------------------------
        def on_mouse_move(sender, app_data, user_data):
            # app_data: {"x": ..., "y": ...}
            runner.queue_input_event(
                EventInfo(
                    kind=EventKind.CURSOR,
                    x=int(app_data["x"]),
                    y=int(app_data["y"]),
                )
            )

        # ------------------------------------------------------------
        # Mouse wheel
        # ------------------------------------------------------------
        def on_mouse_wheel(sender, app_data, user_data):
            # app_data: {"x": ..., "y": ..., "wheel": ..., "clicks": ...}
            runner.queue_input_event(
                EventInfo(
                    kind=EventKind.MOUSE_WHEEL,
                    x=int(app_data["x"]),
                    y=int(app_data["y"]),
                    wheel=int(app_data["wheel"]),
                    clicks=int(app_data["clicks"]),
                )
            )

        # ------------------------------------------------------------
        # Key press
        # ------------------------------------------------------------
        def on_key_press(sender, app_data, user_data):
            # app_data: {"key": ..., "flags": ..., "vkey": ...}
            runner.queue_input_event(
                EventInfo(
                    kind=EventKind.KEY,
                    key=int(app_data["key"]),
                    flags=int(app_data["flags"]),
                    vKey=int(app_data["vkey"]),
                )
            )

        # ------------------------------------------------------------
        # Register callbacks with DearPyGui
        # ------------------------------------------------------------
        dpg.set_mouse_down_callback(on_mouse_down)
        dpg.set_mouse_release_callback(on_mouse_up)
        dpg.set_mouse_move_callback(on_mouse_move)
        dpg.set_mouse_wheel_callback(on_mouse_wheel)
        dpg.set_key_press_callback(on_key_press)

