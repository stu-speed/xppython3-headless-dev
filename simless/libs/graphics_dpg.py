from __future__ import annotations

from typing import Any, TYPE_CHECKING

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_types import DPGCommand, DPGGeom, DPGOp, XPGeom

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class GraphicsDpg:
    # ------------------------------------------------------------------
    # Deferred DearPyGui command queue
    #
    # All DPG mutations are recorded here during callbacks and
    # executed during draw_frame() replay only.
    # ------------------------------------------------------------------
    _dpg_commands: list[DPGCommand]

    font_proportional: int | str
    font_mono = int | str

    fake_xp: FakeXP

    # ------------------------------------------------------------------
    # Initialize font registry and load bundled fonts
    # ------------------------------------------------------------------
    def init_fonts(self):
        """Load proportional + monospaced fonts bundled with FakeXP."""
        font_dir = self.fake_xp._xplane_root / "simless" / "fonts"

        prop_path = font_dir / "DejaVuSans.ttf"
        mono_path = font_dir / "DejaVuSansMono.ttf"

        with dpg.font_registry():  # type: ignore
            self.font_proportional = dpg.add_font(str(prop_path), 14)
            self.font_mono = dpg.add_font(str(mono_path), 14)

        # bind proportional as global default
        dpg.bind_font(self.font_proportional)

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

    def dpg_get_value(self, item: int | str) -> Any:
        return dpg.get_value(item)

    def dpg_set_value(self, item: int | str, value: Any) -> None:
        dpg.set_value(item, value)

    def dpg_is_item_shown(self, item: int | str) -> bool | None:
        return dpg.is_item_shown(item)

    def dpg_get_mouse_pos(self, **kwargs) -> list[int] | tuple[int, ...]:
        return dpg.get_mouse_pos(**kwargs)

    def dpg_get_text_size(self, text: str) -> list[float] | tuple[float, ...]:
        return dpg.get_text_size(text)

    def enqueue_dpg(
            self,
            op: DPGOp,
            target_drawlist: str | int | None = None,
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

    def compute_window_decorations(self, dpg_window_id: str) -> dict[str, Any]:
        """
        Compute XPWidget-style decoration metrics from a DPG window
        using only APIs available in this version of DearPyGui.

        Returns:
            {
                "title_bar": int,
                "border_left": int,
                "border_right": int,
                "border_bottom": int,
                "client_rect": XPGeom,
                "frame_rect": XPGeom,
            }
        """

        screen_h = self.dpg_get_viewport_client_height()

        # ------------------------------------------------------------
        # 1. FRAME RECT (outer window)
        # ------------------------------------------------------------
        fmin_x, fmin_y = dpg.get_item_rect_min(dpg_window_id)
        fmax_x, fmax_y = dpg.get_item_rect_max(dpg_window_id)

        frame = XPGeom(
            left=fmin_x,
            top=screen_h - fmin_y,
            right=fmax_x,
            bottom=screen_h - fmax_y,
        )

        # ------------------------------------------------------------
        # 2. CLIENT RECT (inner drawlist)
        #
        # In your architecture, every WindowEx has:
        #   - a DPG window (frame)
        #   - a DPG drawlist inside it (client)
        #
        # The drawlist tag is stored in WindowExInfo.drawlist_tag.
        # ------------------------------------------------------------
        win_info = self.fake_xp.window_manager.require_info_by_dpg_id(dpg_window_id)
        dl_id = win_info.drawlist_tag
        assert dl_id is not None

        dl_min_x, dl_min_y = dpg.get_item_rect_min(dl_id)
        dl_max_x, dl_max_y = dpg.get_item_rect_max(dl_id)

        client = XPGeom(
            left=dl_min_x,
            top=screen_h - dl_min_y,
            right=dl_max_x,
            bottom=screen_h - dl_max_y,
        )

        # ------------------------------------------------------------
        # 3. DECORATION METRICS
        # ------------------------------------------------------------
        border_left = client.left - frame.left
        border_right = frame.right - client.right
        border_bottom = client.bottom - frame.bottom
        title_bar = frame.top - client.top

        return {
            "title_bar": title_bar,
            "border_left": border_left,
            "border_right": border_right,
            "border_bottom": border_bottom,
            "client_rect": client,
            "frame_rect": frame,
        }

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

            case DPGOp.ADD_CHECKBOX:
                dpg.add_checkbox(*cmd.args, **cmd.kwargs)

            # --------------------------------------------------
            # Menus (XPLMMenus → DearPyGui)
            # --------------------------------------------------
            case DPGOp.ADD_MENU:
                dpg.add_menu(*cmd.args, **cmd.kwargs)

            case DPGOp.ADD_MENU_ITEM:
                dpg.add_menu_item(*cmd.args, **cmd.kwargs)

            case DPGOp.CONFIGURE_ITEM:
                dpg.configure_item(*cmd.args, **cmd.kwargs)

            case DPGOp.DELETE_ITEM:
                dpg.delete_item(*cmd.args, **cmd.kwargs)

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

            case DPGOp.BIND_ITEM_FONT:
                dpg.bind_item_font(*cmd.args)

            # --------------------------------------------------
            # Safety net
            # --------------------------------------------------
            case _:
                raise RuntimeError(f"Unhandled DPG operation: {cmd.op}")

    def _clear_drawlist_children(self, drawlist_id: int | str) -> None:
        """Clear per-frame draw primitives to avoid unbounded accumulation."""
        if not dpg.does_item_exist(drawlist_id):
            return
        dpg.delete_item(drawlist_id, children_only=True)

    def _window_ex_apply_xp_to_dpg(self):
        """Apply XP→DPG geometry using XPGeom/DPGGeom conversions."""

        client_h = dpg.get_viewport_client_height()

        for info in self.fake_xp.window_manager.all_info():
            if not info._dirty_xp_to_dpg:
                continue

            dpg_id = info.dpg_tag
            assert dpg_id is not None

            if not dpg.does_item_exist(dpg_id):
                print(f"[XP→DPG] SKIP: DPG item missing for wid={info.wid}")
                continue

            xp_geom = info.frame

            # Convert XP → DPG
            dpg_geom = xp_geom.to_dpg(client_h)

            # Apply geometry
            dpg.configure_item(
                dpg_id,
                pos=(dpg_geom.x, dpg_geom.y),
                width=dpg_geom.width,
                height=dpg_geom.height,
            )

    def _window_ex_read_dpg_to_xp(self):
        """
        Read DPG geometry after render and update XP geometry.

        DPG is authoritative here (user dragging/resizing).
        XP geometry is updated WITHOUT marking dirty_xp_to_dpg.
        """

        client_h = dpg.get_viewport_client_height()

        for info in self.fake_xp.window_manager.all_info():
            dpg_id = info.dpg_tag
            assert dpg_id is not None
            dl_id = info.drawlist_tag
            assert dl_id is not None

            if not dpg.does_item_exist(dpg_id) or not dpg.does_item_exist(dl_id):
                continue

            # Read DPG window geometry
            try:
                win_x, win_y = dpg.get_item_pos(dpg_id)
                win_w = dpg.get_item_width(dpg_id)
                assert win_w
                win_h = dpg.get_item_height(dpg_id)
                assert win_h
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
