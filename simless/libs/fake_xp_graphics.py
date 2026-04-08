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

from typing import Any, Optional

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_graphics_api import FakeXPGraphicsAPI
from simless.libs.fake_xp_types import DPGCommand, DPGGeom, DPGOp, EventInfo, EventKind
from simless.libs.window import WindowManager
from XPPython3.xp_typing import (
    XPLMMenuID
)


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
        self._current_window_ex = None
        self._keyboard_focus_window = None
        self._menus = {}
        self._next_menu_id = 1
        self._menu_callbacks = {}
        self._root_plugins_menu = None

        self._dpg_commands = []

        self.window_manager = WindowManager(self.fake_xp)

    # ----------------------------------------------------------------------
    # DPG INITIALIZATION
    # ----------------------------------------------------------------------
    def init_graphics_root(self) -> None:
        dpg.create_context()
        dpg.create_viewport(
            title="Fake X-Plane",
            width=1920,
            height=1080,
        )

        # --------------------------------------------------------------
        # 1. Finalize DPG internals BEFORE creating menu bar
        # --------------------------------------------------------------
        dpg.setup_dearpygui()

        # --------------------------------------------------------------
        # 2. Now it is legal to create the menu bar
        # --------------------------------------------------------------
        self._init_menu_bar()

        # --------------------------------------------------------------
        # 3. Create viewport drawlists (legal after setup)
        # --------------------------------------------------------------
        self._screen_drawlist_back = dpg.add_viewport_drawlist(front=False)
        self._screen_drawlist_front = dpg.add_viewport_drawlist(front=True)
        self._active_drawlist = self._screen_drawlist_back

        # --------------------------------------------------------------
        # 4. Show the viewport
        # --------------------------------------------------------------
        dpg.show_viewport()

        # --------------------------------------------------------------
        # 5. Install input callbacks AFTER viewport is visible
        # --------------------------------------------------------------
        self._install_dpg_input_callbacks()

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
            self.fake_xp.simless_runner.end_run_loop()
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
        self.fake_xp.window_manager.clear_dirty_xp_to_dpg()

        # 7) Read DPG→XP geometry
        self._window_ex_read_dpg_to_xp()

        # 8) Consume DPG→XP geometry changes
        self._consume_dpg_to_xp_changes()

        # 9) Input processing
        for event in self.fake_xp.drain_input_events():
            self.fake_xp.process_event_info(event)

        # 10) WindowEx drawing (enqueue only)
        for info in self.fake_xp.window_manager.all_info():
            if not info.visible or info.draw_cb is None:
                continue

            self._clear_drawlist_children(info.drawlist_tag)

            prev_drawlist = self._active_drawlist
            prev_window = self._current_window_ex
            try:
                self._active_drawlist = info.drawlist_tag
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
        self.fake_xp.render_widget_frame()

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
        target_drawlist: str | None = None,
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
        """Execute a single DearPyGui command immediately."""

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
            # Menus (XPLMMenus → DearPyGui)
            # --------------------------------------------------
            case DPGOp.ADD_MENU:
                dpg.add_menu(*cmd.args, **cmd.kwargs)

            case DPGOp.ADD_MENU_ITEM:
                label = cmd.kwargs["label"]
                parent = cmd.kwargs["parent"]
                tag = cmd.kwargs["tag"]

                dpg.add_menu_item(
                    label=label,
                    parent=parent,
                    tag=tag,
                    callback=self._dispatch_menu_click
                )

            case DPGOp.ADD_MENU_SEPARATOR:
                dpg.add_separator(*cmd.args, **cmd.kwargs)

            case DPGOp.SET_MENU_ITEM_CHECKED:
                # DearPyGui uses configure_item(check=True/False)
                menu_item_tag, checked = cmd.args
                dpg.configure_item(menu_item_tag, check=checked)

            case DPGOp.SET_MENU_ITEM_ENABLED:
                menu_item_tag, enabled = cmd.args
                dpg.configure_item(menu_item_tag, enabled=enabled)

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

    def _clear_drawlist_children(self, drawlist_id: Optional[str]) -> None:
        """Clear per-frame draw primitives to avoid unbounded accumulation."""
        if drawlist_id is None:
            return
        if not dpg.does_item_exist(drawlist_id):
            return
        dpg.delete_item(drawlist_id, children_only=True)

    def _install_dpg_input_callbacks(self) -> None:
        xp = self.fake_xp  # FakeXP instance

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
        """Apply XP→DPG geometry using XPGeom/DPGGeom conversions."""

        client_h = dpg.get_viewport_client_height()

        for info in self.fake_xp.window_manager.all_info():
            if not info._dirty_xp_to_dpg:
                continue

            wid = info.wid
            dpg_id = info.dpg_tag

            if not dpg.does_item_exist(dpg_id):
                print(f"[XP→DPG] SKIP: DPG item missing for wid={wid}")
                continue

            xp_geom = info.frame
            print(f"[XP→DPG] wid={wid} XPGeom: {xp_geom}")

            # Convert XP → DPG
            dpg_geom = xp_geom.to_dpg(client_h)
            print(f"[XP→DPG] wid={wid} computed DPGGeom: {dpg_geom}")

            # Apply geometry
            dpg.configure_item(
                dpg_id,
                pos=(dpg_geom.x, dpg_geom.y),
                width=dpg_geom.width,
                height=dpg_geom.height,
            )

            # Read back what DPG actually applied
            applied_pos = dpg.get_item_pos(dpg_id)
            applied_size = (
                dpg.get_item_width(dpg_id),
                dpg.get_item_height(dpg_id),
            )

            print(f"[XP→DPG] wid={wid} DPG applied: pos={applied_pos} size={applied_size}")

            dx = applied_pos[0] - dpg_geom.x
            dy = applied_pos[1] - dpg_geom.y
            dw = applied_size[0] - dpg_geom.width
            dh = applied_size[1] - dpg_geom.height

            print(f"[XP→DPG] wid={wid} Δpos=({dx}, {dy}) Δsize=({dw}, {dh})")

    def _window_ex_read_dpg_to_xp(self):
        """
        Read DPG geometry after render and update XP geometry.

        DPG is authoritative here (user dragging/resizing).
        XP geometry is updated WITHOUT marking dirty_xp_to_dpg.
        """

        client_h = dpg.get_viewport_client_height()

        for info in self.fake_xp.window_manager.all_info():
            dpg_id = info.dpg_tag
            dl_id = info.drawlist_tag

            if not dpg.does_item_exist(dpg_id) or not dpg.does_item_exist(dl_id):
                continue

            # Read DPG window geometry
            try:
                win_x, win_y = dpg.get_item_pos(dpg_id)
                win_w = dpg.get_item_width(dpg_id)
                win_h = dpg.get_item_height(dpg_id)
            except Exception:
                continue

            # Convert to XPGeom via DPGGeom
            dpg_geom = DPGGeom(win_x, win_y, win_w, win_h)
            xp_frame = dpg_geom.to_xp(client_h)

            if info.frame != xp_frame:
                info.set_frame_from_dpg(dpg_geom, client_h)

            # Read DPG drawlist rect → XP client rect
            dl_min_x, dl_min_y = dpg.get_item_rect_min(dl_id)
            dl_max_x, dl_max_y = dpg.get_item_rect_max(dl_id)

            dpg_client_geom = DPGGeom(
                dl_min_x,
                dl_min_y,
                dl_max_x - dl_min_x,
                dl_max_y - dl_min_y,
            )
            xp_client = dpg_client_geom.to_xp(client_h)

            if info.client != xp_client:
                info.set_client_from_dpg(dpg_client_geom, client_h)

    def _consume_dpg_to_xp_changes(self) -> None:
        """React to DPG-side geometry changes."""

        for info in self.fake_xp.window_manager.all_info():
            if not info._dirty_dpg_to_xp:
                continue

            # Optional: fire XP callbacks here

            info._dirty_dpg_to_xp = False

    def _init_menu_bar(self) -> None:
        """Create the top-level X-Plane-style menu bar on the viewport."""

        dpg_tag = "xp_menu_plugins"
        with dpg.viewport_menu_bar(tag="xp_menu_bar"):
            with dpg.menu(label="File", tag="xp_menu_file"):
                dpg.add_menu_item(
                    label="Quit",
                    tag="xp_menu_file_quit",
                    callback=lambda: self.fake_xp.simless_runner.end_run_loop()
                )

            # The actual DPG root for plugin menus
            dpg.add_menu(
                label="Plugins",
                tag=dpg_tag
            )

        # Allocate a real XP menu ID for the plugin vroot
        root_id = XPLMMenuID(self._next_menu_id)
        self._next_menu_id += 1

        self._root_plugins_menu = root_id

        self._menus[root_id] = {
            "name": "Plugins",
            "parent": None,
            "parent_item": None,
            "handler": None,
            "refcon": None,
            "items": [],
            "dpg_tag": dpg_tag,
        }

    def _dispatch_menu_click(self, sender, app_data):
        tag = sender  # DPG gives us the authoritative tag

        # Search all menus for this item tag
        for menu_id, menu in self._menus.items():
            for index, item in enumerate(menu["items"]):
                if item.get("tag") == tag:
                    handler = menu["handler"]
                    if handler:
                        handler(menu["refcon"], item["refcon"])
                    return

        # If we get here, the tag was not found — this is a real error
        raise KeyError(f"[FakeXP] Menu item tag not found: {tag}")
