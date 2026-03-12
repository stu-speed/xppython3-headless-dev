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

from typing import Any, Callable, Optional

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_graphics_api import FakeXPGraphicsAPI
from simless.libs.fake_xp_types import DPGCommand, DPGOp, EventInfo, EventKind

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

    # ------------------------------------------------------------------
    # Deferred DearPyGui command queue
    #
    # All DPG mutations are recorded here during callbacks and
    # executed during draw_frame() replay only.
    # ------------------------------------------------------------------
    _dpg_commands: list[DPGCommand]

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
        "dpg_is_item_shown",
        "dpg_is_dearpygui_running",
        "dpg_does_item_exist",
        "dpg_get_viewport_client_width",
        "dpg_get_viewport_client_height",
        "dpg_get_mouse_pos",
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
        self._windows_ex = {}
        self._current_window_ex = None
        self._next_window_id = 1
        self._keyboard_focus_window = None

        self._dpg_commands = []

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
          - Input handlers

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

        self._install_dpg_input_callbacks()

        self._context_ready = True
        self._layout_ready = False

    # ----------------------------------------------------------------------
    # FRAME RENDERING
    # ----------------------------------------------------------------------
    def draw_frame(self) -> None:
        """Render one simless frame.

        Ordering:
          1) If viewport closed, end run loop.
          2) Execute XP draw callbacks (screen-level) to enqueue commands.
          3) Execute deferred DearPyGui commands (screen + windows).
          4) Render one DearPyGui frame (flush drawlists).
          5) Execute WindowEx draw callbacks (enqueue window-local commands).
          6) Execute deferred DearPyGui commands (window-local).
          7) On first rendered frame, set layout_ready and return.
          8) After layout_ready, render widget frame.
        """
        self._require_context()

        # --------------------------------------------------------------
        # 1) If viewport closed, end run loop
        # --------------------------------------------------------------
        if not dpg.is_dearpygui_running():
            self.xp.simless_runner.end_run_loop()
            return

        # --------------------------------------------------------------
        # 2) Clear global screen draw surfaces
        #
        # Drawlists are persistent; children must be cleared each frame
        # to avoid accumulation.
        # --------------------------------------------------------------
        self._clear_drawlist_children(self._screen_drawlist_back)
        self._clear_drawlist_children(self._screen_drawlist_front)

        # --------------------------------------------------------------
        # 3) Global screen drawing (XPLMGraphics)
        #
        # XP semantics:
        #   - Deterministic phase ordering
        #   - wantsBefore=1 callbacks before wantsBefore=0
        #
        # Callbacks enqueue DPGCommand objects only.
        # --------------------------------------------------------------
        self._active_drawlist = self._screen_drawlist_back

        phases = sorted({phase for _, phase, _ in self._draw_callbacks})
        for phase in phases:
            for wants_before in (1, 0):
                for cb, cb_phase, cb_wants_before in list(self._draw_callbacks):
                    if cb_phase == phase and cb_wants_before == wants_before:
                        cb(phase, wants_before)

        # --------------------------------------------------------------
        # 4) Execute deferred DPG commands (screen-level)
        #
        # This is the ONLY place where DearPyGui is mutated.
        # --------------------------------------------------------------
        for cmd in self._dpg_commands:
            if cmd.target_drawlist is not None:
                dpg.push_container_stack(cmd.target_drawlist)
                try:
                    self.xp.execute_dpg_command(cmd)
                finally:
                    dpg.pop_container_stack()
            else:
                self.xp.execute_dpg_command(cmd)

        self._dpg_commands.clear()

        # --------------------------------------------------------------
        # 5) Render one DearPyGui frame
        #
        # Flushes all drawlists and establishes valid item state.
        # --------------------------------------------------------------
        dpg.render_dearpygui_frame()

        # Layout is ready after first dpg frame
        if not self._layout_ready:
            self._layout_ready = True

            for info in self._iter_window_ex_in_layer_order():
                if info.visible and not info.geom_applied:
                    self._apply_window_geometry(info.wid, info.geometry)
                    info.geom_applied = True

        # --------------------------------------------------------------
        # Input processing (WindowEx + keyboard)
        # --------------------------------------------------------------
        events = self.xp.drain_input_events()
        for event in events:
            self.xp.process_event_info(event)

        # --------------------------------------------------------------
        # 6) WindowEx drawing (graphics-owned windows)
        #
        # Window draw callbacks enqueue window-local commands.
        # --------------------------------------------------------------
        for info in self._iter_window_ex_in_layer_order():
            if not info.visible or info.draw_cb is None:
                continue

            self._clear_drawlist_children(info.drawlist_id)

            prev_drawlist = self._active_drawlist
            prev_window = self._current_window_ex
            try:
                self._active_drawlist = info.drawlist_id
                self._current_window_ex = info
                info.draw_cb(info.wid, info.refcon)
            finally:
                self._active_drawlist = prev_drawlist
                self._current_window_ex = prev_window

        # --------------------------------------------------------------
        # 7) Execute deferred DPG commands (window-level)
        # --------------------------------------------------------------
        for cmd in self._dpg_commands:
            if cmd.op.name.startswith("DRAW") and cmd.target_drawlist is None:
                raise RuntimeError(f"DRAW command missing target_drawlist: {cmd}")

        for cmd in self._dpg_commands:
            if cmd.target_drawlist is not None:
                dpg.push_container_stack(cmd.target_drawlist)
                try:
                    self.xp.execute_dpg_command(cmd)
                finally:
                    dpg.pop_container_stack()
            else:
                self.xp.execute_dpg_command(cmd)

        self._dpg_commands.clear()

        # --------------------------------------------------------------
        # 8) Widget rendering (geometry-safe)
        # --------------------------------------------------------------
        self.xp.render_widget_frame()

    # ----------------------------------------------------------------------
    # DPG HELPERS (GRAPHICS-OWNED, FAIL-FAST)
    # ----------------------------------------------------------------------
    def enqueue_dpg(
        self,
        op: DPGOp,
        *,
        target_drawlist: int | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Record a deferred DearPyGui operation.

        This is the only place where DPGCommand objects are created.
        No DPG calls are allowed here.
        """

        self._require_context()

        if kwargs is None:
            kwargs = {}

        self._dpg_commands.append(
            DPGCommand(
                op=op,
                target_drawlist=target_drawlist,
                args=args,
                kwargs=kwargs,
            )
        )

    def dpg_is_dearpygui_running(self) -> bool:
        self._require_context()
        return dpg.is_dearpygui_running()

    def dpg_does_item_exist(self, item: int | str) -> bool:
        self._require_context()
        return dpg.does_item_exist(item)

    def dpg_get_viewport_client_width(self) -> int:
        self._require_context()
        self._require_layout()
        return dpg.get_viewport_client_width()

    def dpg_get_viewport_client_height(self) -> int:
        self._require_context()
        self._require_layout()
        return dpg.get_viewport_client_height()

    def dpg_is_item_shown(self, item: int | str) -> bool:
        self._require_context()
        return dpg.is_item_shown(item)

    def dpg_get_mouse_pos(self, **kwargs) -> list[int] | tuple[int, ...]:
        self._require_context()
        return dpg.get_mouse_pos(**kwargs)

    # ----------------------------------------------------------------------
    # INTERNAL HELPERS
    # ----------------------------------------------------------------------
    def _apply_window_geometry(self, wid, geometry):
        left, top, right, bottom = geometry
        client_h = dpg.get_viewport_client_height()

        dpg.set_item_pos(
            f"xplm_window_{wid}",
            [left, client_h - top],
        )

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
        xp = self.xp  # FakeXP instance

        with dpg.handler_registry():
            dpg.add_mouse_down_handler(
                callback=lambda sender, app_data: (
                    None
                    if not self._layout_ready
                    else xp.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.MOUSE_BUTTON,
                            dpg_x=int(dpg.get_mouse_pos()[0]),
                            dpg_y=int(dpg.get_mouse_pos()[1]),
                            dpg_vp_height=dpg.get_viewport_height(),
                            state="down",
                            button=int(app_data) if isinstance(app_data, int) else 0,
                        )
                    )
                )
            )

            dpg.add_mouse_release_handler(
                callback=lambda sender, app_data: (
                    None
                    if not self._layout_ready
                    else xp.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.MOUSE_BUTTON,
                            dpg_x=int(dpg.get_mouse_pos(local=False)[0]),
                            dpg_y=int(dpg.get_mouse_pos(local=False)[1]),
                            dpg_vp_height=dpg.get_viewport_client_height(),
                            state="up",
                            button=int(app_data) if isinstance(app_data, int) else 0,
                        )
                    )
                )
            )

            dpg.add_mouse_move_handler(
                callback=lambda sender, app_data: (
                    None
                    if not self._layout_ready
                    else xp.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.CURSOR,
                            dpg_x=int(dpg.get_mouse_pos(local=False)[0]),
                            dpg_y=int(dpg.get_mouse_pos(local=False)[1]),
                            dpg_vp_height=dpg.get_viewport_client_height(),
                        )
                    )
                )
            )

            dpg.add_mouse_wheel_handler(
                callback=lambda sender, app_data: (
                    None
                    if not self._layout_ready
                    else xp.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.MOUSE_WHEEL,
                            dpg_x=int(dpg.get_mouse_pos(local=False)[0]),
                            dpg_y=int(dpg.get_mouse_pos(local=False)[1]),
                            dpg_vp_height=dpg.get_viewport_client_height(),
                            wheel=int(app_data),
                            clicks=int(app_data),
                        )
                    )
                )
            )

            dpg.add_key_press_handler(
                callback=lambda sender, app_data: (
                    None
                    if not self._layout_ready
                    else xp.queue_input_event(
                        EventInfo.from_xp(
                            kind=EventKind.KEY,
                            key=int(app_data),
                            flags=0,
                            vKey=int(app_data),
                        )
                    )
                )
            )

    def execute_dpg_command(self, cmd: DPGCommand) -> None:
        """Execute a single DearPyGui command immediately.

        This is the sole execution choke-point for all DearPyGui mutations.

        Lifecycle enforcement:
          - A DearPyGui context must exist
          - DearPyGui must still be running
          - Layout readiness is required ONLY for geometry-dependent commands

        Caller responsibilities:
          - Ensure this is not invoked from plugin callbacks
          - Ensure the correct container stack has already been pushed
            if cmd.target_drawlist is set
        """

        # Hard invariants — programmer error if violated
        assert isinstance(cmd, DPGCommand), "Expected DPGCommand"
        assert isinstance(cmd.op, DPGOp), f"Invalid DPGOp: {cmd.op}"

        # Context + runtime guards
        self._require_context()
        self._require_running()

        # --------------------------------------------------
        # Layout-dependent operations
        #
        # These require a resolved viewport and stable geometry.
        # --------------------------------------------------
        if cmd.op in (
                DPGOp.DRAW_TEXT,
                DPGOp.DRAW_RECTANGLE,
        ):
            self._require_layout()

        match cmd.op:
            # --------------------------------------------------
            # Drawing primitives (layout-dependent)
            # --------------------------------------------------
            case DPGOp.DRAW_TEXT:
                dpg.draw_text(*cmd.args, **cmd.kwargs)

            case DPGOp.DRAW_RECTANGLE:
                dpg.draw_rectangle(*cmd.args, **cmd.kwargs)

            # --------------------------------------------------
            # Containers / widgets (structural creation)
            # --------------------------------------------------
            case DPGOp.ADD_DRAWLIST:
                dpg.add_drawlist(*cmd.args, **cmd.kwargs)

            case DPGOp.ADD_WINDOW:
                dpg.add_window(*cmd.args, **cmd.kwargs)

            case DPGOp.ADD_CHILD_WINDOW:
                dpg.add_child_window(*cmd.args, **cmd.kwargs)

            case DPGOp.ADD_TEXT:
                dpg.add_text(*cmd.args, **cmd.kwargs)

            case DPGOp.ADD_INPUT_TEXT:
                dpg.add_input_text(*cmd.args, **cmd.kwargs)

            case DPGOp.ADD_SLIDER_INT:
                dpg.add_slider_int(*cmd.args, **cmd.kwargs)

            case DPGOp.ADD_BUTTON:
                dpg.add_button(*cmd.args, **cmd.kwargs)

            # --------------------------------------------------
            # Item mutation
            # --------------------------------------------------
            case DPGOp.CONFIGURE_ITEM:
                dpg.configure_item(*cmd.args, **cmd.kwargs)

            case DPGOp.SET_VALUE:
                dpg.set_value(*cmd.args, **cmd.kwargs)

            case DPGOp.SHOW_ITEM:
                dpg.show_item(*cmd.args)

            case DPGOp.HIDE_ITEM:
                dpg.hide_item(*cmd.args)

            case DPGOp.DELETE_ITEM:
                dpg.delete_item(*cmd.args)

            # --------------------------------------------------
            # Safety net
            # --------------------------------------------------
            case _:
                raise RuntimeError(f"Unhandled DPG operation: {cmd.op}")
