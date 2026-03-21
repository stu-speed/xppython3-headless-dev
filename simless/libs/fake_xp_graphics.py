# ===========================================================================
# FakeXPGraphics — DearPyGui-backed graphics subsystem mixin for FakeXP
#
# ROLE
#   Provide a minimal, deterministic façade that mirrors the public
#   XPLMGraphics API surface for simless execution. This subsystem
#   implements only the observable behavior required by plugins and
#   never infers semantics or performs layout.
#
# DESIGN PRINCIPLES
#   - Match the xp.* graphics API contract exactly (xp.pyi).
#   - Never mutate SDK-shaped objects or reinterpret plugin intent.
#   - All returned values come from explicit internal state; no hidden
#     transforms, no heuristics, no auto-layout.
#   - Geometry sync is explicit and deterministic:
#         XP → DPG before render
#         DPG → XP after render
#
# SIMLESS RULES
#   - DearPyGui is used strictly as a visualization backend and is
#     never exposed to plugins.
#   - The DPG context, viewport, and root graphics surface are created
#     before plugin enable and remain stable for the lifetime of FakeXP.
#   - XP draw callbacks are driven by FakeXP’s frame loop, not DPG.
#   - DPG is mutated only at two safe points:
#         (1) before render (XP→DPG apply)
#         (2) after window draw callbacks (window-level commands)
#
# WINDOWEX GEOMETRY MODEL
#   - Each WindowEx has authoritative XP geometry:
#         frame  = desired XP frame rect
#         client = desired XP client rect (defaults to frame)
#   - XP sets geometry via API calls → marks dirty_xp_to_dpg.
#   - DPG user actions (drag/resize) update geometry after render →
#     marks dirty_dpg_to_xp.
#   - No lifecycle flags, no pending states, no multi-frame hazards.
#
# GOAL
#   Provide a contributor-proof, reload-safe, deterministic graphics
#   subsystem that behaves like X-Plane’s XPLMGraphics layer while
#   remaining simple enough for simless GUI testing.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Optional

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_graphics_api import FakeXPGraphicsAPI
from simless.libs.fake_xp_types import DPGCommand, DPGOp, EventInfo, EventKind, WindowExInfo
from XPPython3.xp_typing import XPLMWindowID

DPGCallback = Callable[[int | str, Any, Any], Any]


class FakeXPGraphics(FakeXPGraphicsAPI):
    """DearPyGui-backed graphics subsystem mixin for FakeXP.

    This class owns the DearPyGui lifecycle and exposes:
      - An XPLMGraphics-like API surface (xp.* semantics)
      - A small, explicit set of graphics-owned DearPyGui helpers (dpg_*)
    """

    # ------------------------------------------------------------------
    # Deferred DearPyGui command queue
    #
    # All DPG mutations are recorded here during callbacks and
    # executed during draw_frame() replay only.
    # ------------------------------------------------------------------
    _dpg_commands: list[DPGCommand]

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
        self._screen_drawlist_back = None  # Behind all windows
        self._screen_drawlist_front = None  # Above all windows (optional)
        self._active_drawlist = None
        self._windows_ex = {}
        self._current_window_ex = None
        self._next_window_id = 1
        self._keyboard_focus_window = None

        self._dpg_commands = []

    # ----------------------------------------------------------------------
    # DPG INITIALIZATION
    # ----------------------------------------------------------------------
    def get_windowex(self, win_id: XPLMWindowID) -> WindowExInfo:
        """
        Return the WindowExInfo for the given XPLMWindowID.

        Fail fast:
        - If the window does not exist, raise a clear exception.
        - This prevents silent corruption and makes plugin errors obvious.
        """
        try:
            return self._windows_ex[win_id]
        except KeyError:
            raise KeyError(f"WindowEx {win_id} does not exist") from None

    def all_windowex(self) -> list[WindowExInfo]:
        return list(self._windows_ex.values())

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
        dpg.create_context()
        dpg.create_viewport(
            title="Fake X-Plane",
            width=1920,
            height=1080,
        )
        dpg.setup_dearpygui()
        dpg.show_viewport()

        self._install_dpg_input_callbacks()

        # ------------------------------------------------------------------
        # Global screen draw surfaces (XP graphics layer)
        # ------------------------------------------------------------------

        # Background screen surface (behind all windows)
        self._screen_drawlist_back = dpg.add_viewport_drawlist(front=False)

        # Foreground screen surface (above all windows, optional)
        self._screen_drawlist_front = dpg.add_viewport_drawlist(front=True)

        # Default target for XPLMGraphics calls
        self._active_drawlist = self._screen_drawlist_back

    # ----------------------------------------------------------------------
    # FRAME RENDERING
    # ----------------------------------------------------------------------
    def draw_frame(self) -> None:
        """Render one simless frame.

        Deterministic ordering:

          1) If viewport closed, end run loop.
          2) Clear screen drawlists.
          3) Run XP screen-level draw callbacks (enqueue DPG commands).
          4) Execute deferred DPG commands (screen-level).
          5) Apply XP→DPG geometry.
          6) Render one DearPyGui frame.
          7) Read DPG→XP geometry.
          8) Consume DPG→XP geometry changes.
          9) Process input events.
         10) Run WindowEx draw callbacks (enqueue window-local commands).
         11) Execute deferred DPG commands (window-level).
         12) Render widget frame.
        """

        # 1) End run loop if viewport closed
        if not dpg.is_dearpygui_running():
            self.xp.simless_runner.end_run_loop()
            return

        # 2) Clear global screen drawlists
        self._clear_drawlist_children(self._screen_drawlist_back)
        self._clear_drawlist_children(self._screen_drawlist_front)

        # 3) XP screen-level drawing (enqueue only)
        self._active_drawlist = self._screen_drawlist_back
        phases = sorted({phase for _, phase, _ in self._draw_callbacks})
        for phase in phases:
            for wants_before in (1, 0):
                for cb, cb_phase, cb_wants_before in list(self._draw_callbacks):
                    if cb_phase == phase and cb_wants_before == wants_before:
                        cb(phase, wants_before)

        # 4) Execute deferred DPG commands (screen-level)
        for cmd in self._dpg_commands:
            if cmd.target_drawlist is not None:
                dpg.push_container_stack(cmd.target_drawlist)
                try:
                    self._execute_dpg_command(cmd)
                finally:
                    dpg.pop_container_stack()
            else:
                self._execute_dpg_command(cmd)
        self._dpg_commands.clear()

        # 5) Apply XP→DPG geometry
        self._window_ex_apply_xp_to_dpg()

        # 6) Render one DearPyGui frame
        dpg.render_dearpygui_frame()

        # XP→DPG push is complete after render
        for info in self._windows_ex.values():
            info.dirty_xp_to_dpg = False

        # 7) Read DPG→XP geometry
        self._window_ex_read_dpg_to_xp()

        # 8) Consume DPG→XP geometry changes
        self._consume_dpg_to_xp_changes()

        # 9) Input processing
        for event in self.xp.drain_input_events():
            self.xp.process_event_info(event)

        # 10) WindowEx drawing (enqueue only)
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

        # 11) Execute deferred DPG commands (window-level)
        for cmd in self._dpg_commands:
            if cmd.op.name.startswith("DRAW") and cmd.target_drawlist is None:
                raise RuntimeError(f"DRAW command missing target_drawlist: {cmd}")

        for cmd in self._dpg_commands:
            if cmd.target_drawlist is not None:
                dpg.push_container_stack(cmd.target_drawlist)
                try:
                    self._execute_dpg_command(cmd)
                finally:
                    dpg.pop_container_stack()
            else:
                self._execute_dpg_command(cmd)
        self._dpg_commands.clear()

        # 12) Widget rendering
        self.xp.render_widget_frame()

    # ----------------------------------------------------------------------
    # DPG HELPERS (ALL DPG calls handled by this class)
    # ----------------------------------------------------------------------
    def dpg_is_dearpygui_running(self) -> bool:
        return dpg.is_dearpygui_running()

    def dpg_does_item_exist(self, item: int | str) -> bool:
        return dpg.does_item_exist(item)

    def dpg_get_viewport_client_width(self) -> int:
        return dpg.get_viewport_client_width()

    def dpg_get_viewport_client_height(self) -> int:
        return dpg.get_viewport_client_height()

    def dpg_is_item_shown(self, item: int | str) -> bool:
        return dpg.is_item_shown(item)

    def dpg_get_mouse_pos(self, **kwargs) -> list[int] | tuple[int, ...]:
        return dpg.get_mouse_pos(**kwargs)

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

    # ----------------------------------------------------------------------
    # INTERNAL HELPERS
    # ----------------------------------------------------------------------

    def _execute_dpg_command(self, cmd: DPGCommand) -> None:
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
                    xp.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.MOUSE_BUTTON,
                            dpg_x=int(dpg.get_mouse_pos(local=False)[0]),
                            dpg_y=int(dpg.get_mouse_pos(local=False)[1]),
                            dpg_vp_height=dpg.get_viewport_client_height(),
                            state="down",
                            button=int(app_data) if isinstance(app_data, int) else 0,
                        )
                    )
                )
            )

            dpg.add_mouse_release_handler(
                callback=lambda sender, app_data: (
                    xp.queue_input_event(
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
                    xp.queue_input_event(
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
                    xp.queue_input_event(
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
                    xp.queue_input_event(
                        EventInfo.from_xp(
                            kind=EventKind.KEY,
                            key=int(app_data),
                            flags=0,
                            vKey=int(app_data),
                        )
                    )
                )
            )

    def _window_ex_apply_xp_to_dpg(self):
        """Apply XP→DPG geometry before rendering.

        XP is authoritative when XP code changes geometry.
        Only runs when dirty_xp_to_dpg is True.
        """

        client_h = dpg.get_viewport_client_height()

        for wid, info in self._windows_ex.items():
            if not info.dirty_xp_to_dpg:
                continue

            dpg_id = info.dpg_window_id
            if not dpg.does_item_exist(dpg_id):
                continue

            if info.frame is None:
                continue

            left, top, right, bottom = info.frame

            width = max(1, right - left)
            height = max(1, top - bottom)

            dpg_x = left
            dpg_y = client_h - top

            dpg.configure_item(
                dpg_id,
                pos=(dpg_x, dpg_y),
                width=width,
                height=height,
            )

    def _window_ex_read_dpg_to_xp(self):
        """Read DPG geometry after render and update XP geometry.

        Detects DPG-side movement/resizing and sets dirty_dpg_to_xp.
        Always runs AFTER dpg.render_dearpygui_frame().
        """

        client_h = dpg.get_viewport_client_height()

        for wid, info in self._windows_ex.items():
            dpg_id = info.dpg_window_id
            dl_id = info.drawlist_id

            if not dpg.does_item_exist(dpg_id) or not dpg.does_item_exist(dl_id):
                continue

            # ----------------------------------------------------------
            # Read DPG window geometry
            # ----------------------------------------------------------
            try:
                win_x, win_y = dpg.get_item_pos(dpg_id)
                win_w = dpg.get_item_width(dpg_id)
                win_h = dpg.get_item_height(dpg_id)
            except Exception:
                continue

            # Convert to XP frame rect
            new_frame = (
                win_x,
                client_h - win_y,
                win_x + win_w,
                client_h - win_y - win_h,
            )

            # Detect change BEFORE updating stored geometry
            if info.frame != new_frame:
                info.dirty_dpg_to_xp = True

            info.frame = new_frame

            # ----------------------------------------------------------
            # Read DPG drawlist rect → XP client rect
            # ----------------------------------------------------------
            dl_min_x, dl_min_y = dpg.get_item_rect_min(dl_id)
            dl_max_x, dl_max_y = dpg.get_item_rect_max(dl_id)

            new_client = (
                dl_min_x,
                client_h - dl_min_y,
                dl_max_x,
                client_h - dl_max_y,
            )

            if info.client != new_client:
                info.dirty_dpg_to_xp = True

            info.client = new_client

    def _consume_dpg_to_xp_changes(self) -> None:
        """React to DPG-side geometry changes.

        _window_ex_geometry_update() has already updated info.frame/client
        and set dirty_dpg_to_xp = True if geometry changed.
        XP now acknowledges the change and clears the flag.
        """

        for info in self._windows_ex.values():
            if not info.dirty_dpg_to_xp:
                continue

            # Optional: fire XP callbacks or update window manager state here.
            # (Currently no extra processing needed.)

            # Acknowledge the change.
            info.dirty_dpg_to_xp = False
