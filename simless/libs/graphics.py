# ===========================================================================
# GraphicsManager — DearPyGui-backed renderer for FakeXP
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

from typing import Any, Callable, Dict, List, Optional

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_types import (
    WindowExInfo
)
from simless.libs.graphics_dpg import GraphicsDpg
from XPPython3.xp_typing import XPLMMenuID, XPLMWindowID


class GraphicsManager(GraphicsDpg):
    # ------------------------------------------------------------------
    # XPLMGraphics draw callbacks
    #
    # Registered via registerDrawCallback().
    # Stored as (callback, phase, wants_before).
    # Executed during draw_frame() to enqueue draw commands.
    # ------------------------------------------------------------------
    _draw_callbacks: List[
        tuple[
            Callable[[int, int], Any],  # callback(phase, wants_before)
            int,  # phase
            int  # wants_before (1 or 0)
        ]
    ]

    # ------------------------------------------------------------------
    # Texture bookkeeping (simless stub)
    #
    # Texture IDs are allocated deterministically but not backed
    # by real GPU resources.
    # ------------------------------------------------------------------
    _next_tex_id: int
    _textures: Dict[int, Any]

    # ------------------------------------------------------------------
    # Global screen draw surfaces
    #
    # Viewport-attached drawlists representing the X-Plane screen.
    # These are not WindowEx windows.
    #
    # Screen-level XPLMGraphics calls enqueue commands targeting
    # _active_drawlist.
    # ------------------------------------------------------------------
    _screen_drawlist_back: Optional[str]  # Behind all windows
    _screen_drawlist_front: Optional[str]  # Above all windows

    # Currently selected draw target for XPLMGraphics enqueue.
    # Switched temporarily while processing WindowEx draw callbacks.
    _active_drawlist: Optional[str]

    # ----------------------------------------------------------------------
    # INITIALIZATION
    # ----------------------------------------------------------------------
    def __init__(self, fake_xp):
        """Initialize internal graphics state.

        This sets up *graphics-layer* bookkeeping only.
        It does NOT create any widgets or windows and does NOT
        initialize DearPyGui itself.
        """
        self.fake_xp = fake_xp

        # Screen-level draw callbacks
        self._draw_callbacks = []

        # Texture bookkeeping
        self._next_tex_id = 1
        self._textures = {}

        # Global screen drawlists
        self._screen_drawlist_back = None  # Behind all windows
        self._screen_drawlist_front = None  # Above all windows (optional)

        # Dynamic draw context
        self._active_drawlist = None
        self._current_window_ex = None

        # Input focus (owned by InputManager, but renderer stores the tag)
        self._keyboard_focus_window = None

        # Menu bookkeeping (renderer owns DPG menus)
        self._menus = {}
        self._next_menu_id = 1
        self._menu_callbacks = {}
        self._root_plugins_menu = None

        # Deferred DPG command queue
        self._dpg_commands = []

    # ----------------------------------------------------------------------
    # API HELPERS
    # ----------------------------------------------------------------------
    def get_draw_callbacks(self) -> List[
        tuple[Callable[[int, int], Any], int, int]
    ]:
        """Return a snapshot of registered XPLMGraphics draw callbacks."""
        return list(self._draw_callbacks)

    def register_draw_callback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wants_before: int,
    ) -> None:
        """Public API: register a draw callback."""
        self._draw_callbacks.append((cb, phase, wants_before))

    def unregister_draw_callback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wants_before: int,
    ) -> None:
        """Public API: unregister a draw callback."""
        self._draw_callbacks = [
            entry
            for entry in self._draw_callbacks
            if not (entry[0] is cb and entry[1] == phase and entry[2] == wants_before)
        ]

    def get_screen_drawlists(self) -> tuple[
        Optional[str], Optional[str]
    ]:
        """Return (back_drawlist, front_drawlist)."""
        return self._screen_drawlist_back, self._screen_drawlist_front

    def get_active_drawlist(self) -> Optional[str]:
        """Return the currently active drawlist."""
        return self._active_drawlist

    def set_active_drawlist(self, dl: Optional[str]) -> None:
        self._active_drawlist = dl

    def get_current_window(self) -> Optional[WindowExInfo]:
        """Return the WindowExInfo currently being drawn."""
        return self._current_window_ex

    def get_keyboard_focus_window(self) -> Optional[XPLMWindowID]:
        """Return the window ID that currently has keyboard focus."""
        return self._keyboard_focus_window

    def get_texture_ids(self) -> List[int]:
        """Return a list of allocated fake texture IDs."""
        return list(self._textures.keys())

    def get_texture_map(self) -> Dict[int, Any]:
        """Return the internal texture map (read-only)."""
        return dict(self._textures)

    def get_root_plugins_menu(self) -> Optional[XPLMMenuID]:
        """Return the root Plugins menu ID."""
        return self._root_plugins_menu

    def has_menu(self, menu_id: XPLMMenuID) -> bool:
        """Return True if menu_id exists in the registry."""
        return menu_id in self._menus

    def get_menu(self, menu_id: XPLMMenuID) -> Optional[Dict[str, Any]]:
        """Return the menu dict or None."""
        return self._menus.get(menu_id)

    def get_menu_items(self, menu_id: XPLMMenuID) -> Optional[list[Dict[str, Any]]]:
        """Return the list of items for a menu."""
        menu = self._menus.get(menu_id)
        return menu["items"] if menu else None

    def get_menu_parent_tag(self, menu_id: XPLMMenuID) -> Optional[str]:
        """Return the DPG tag for the menu."""
        menu = self._menus.get(menu_id)
        return menu["dpg_tag"] if menu else None

    def allocate_menu_id(self) -> XPLMMenuID:
        """Allocate a new XPLMMenuID."""
        mid = XPLMMenuID(self._next_menu_id)
        self._next_menu_id += 1
        return mid

    def create_menu_record(
        self,
        menu_id: XPLMMenuID,
        name: str,
        parent: XPLMMenuID,
        parent_item: int,
        handler: Optional[Callable[[Any, Any], None]],
        refcon: Any,
        dpg_tag: str,
    ) -> None:
        """Insert a new menu record into the registry."""
        self._menus[menu_id] = {
            "name": name,
            "parent": parent,
            "parent_item": parent_item,
            "handler": handler,
            "refcon": refcon,
            "items": [],
            "dpg_tag": dpg_tag,
        }

        if handler:
            self._menu_callbacks[menu_id] = handler

    def append_menu_item_record(
        self,
        menu_id: XPLMMenuID,
        name: str,
        refcon: Any,
        checked: int,
        enabled: bool,
        separator: bool,
        command: Any,
        tag: str,
    ) -> int:
        """Append a menu item to a menu and return its index."""
        menu = self._menus[menu_id]
        idx = len(menu["items"])

        menu["items"].append(
            {
                "name": name,
                "refcon": refcon,
                "enabled": enabled,
                "checked": checked,
                "separator": separator,
                "command": command,
                "tag": tag,
            }
        )

        return idx

    def set_menu_item_name(self, menu_id: XPLMMenuID, index: int, name: str) -> None:
        self._menus[menu_id]["items"][index]["name"] = name

    def set_menu_item_checked(self, menu_id: XPLMMenuID, index: int, checked: int) -> None:
        self._menus[menu_id]["items"][index]["checked"] = checked

    def set_menu_item_enabled(self, menu_id: XPLMMenuID, index: int, enabled: bool) -> None:
        self._menus[menu_id]["items"][index]["enabled"] = enabled

    def remove_menu_item(self, menu_id: XPLMMenuID, index: int) -> None:
        del self._menus[menu_id]["items"][index]

    def get_menu_handler(self, menu_id: XPLMMenuID) -> Optional[Callable]:
        return self._menu_callbacks.get(menu_id)

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
