from __future__ import annotations

from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_types import (
    DPGCommand, DPGGeom, DPGOp, WindowExInfo
)
from XPPython3.xp_typing import XPLMMenuID, XPLMWindowID

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

    # ------------------------------------------------------------------
    # WindowEx bookkeeping
    #
    # Graphics-owned windows with independent drawlists and callbacks.
    # ------------------------------------------------------------------
    _current_window_ex: Optional[WindowExInfo]

    # Input focus (owned by InputManager, but renderer stores the tag)
    _keyboard_focus_window: Optional[XPLMWindowID]

    # ------------------------------------------------------------------
    # Menu bookkeeping (renderer owns DPG menu structures)
    # ------------------------------------------------------------------
    _menus: Dict[XPLMMenuID, Dict[str, Any]]
    _next_menu_id: int
    _menu_callbacks: Dict[XPLMMenuID, Callable]
    _root_plugins_menu: Optional[XPLMMenuID]

    fake_xp: FakeXP

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
