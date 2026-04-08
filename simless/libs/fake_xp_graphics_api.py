# ===========================================================================
# FakeXPGraphicsAPI — XPLMGraphics-compatible API façade for FakeXP
#
# ROLE
#   Provide a minimal, deterministic implementation of the public
#   xp.graphics API surface for simless execution. This layer exposes
#   only the SDK-shaped functions and returns values derived strictly
#   from FakeXP’s internal state. It performs no layout, inference, or
#   interpretation of plugin intent.
#
# API INVARIANTS
#   - Must match the production xp.* graphics API contract (xp.pyi).
#   - Must not infer semantics, reinterpret arguments, or validate
#     plugin behavior beyond what the real SDK enforces.
#   - Must not mutate SDK-shaped objects or introduce hidden state.
#   - All return values must be deterministic and derived solely from
#     FakeXP’s authoritative geometry and storage.
#
# LIFETIME INVARIANTS
#   - The DearPyGui context, viewport, and root graphics surface are
#     created before plugin enable and remain valid for the entire
#     lifetime of FakeXP.
#   - Therefore, all xp.graphics API calls are always legal; no
#     context-ready gating or deferred initialization is required.
#   - This module never touches DearPyGui directly. All DPG interaction
#     is routed through FakeXPGraphics, which owns the visualization
#     backend and the XP↔DPG geometry sync.
#
# PURPOSE
#   Provide a contributor-proof, reload-safe, SDK-faithful graphics API
#   façade that plugins can rely on during simless execution, without
#   exposing or depending on DearPyGui internals.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, cast, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

from simless.libs.fake_xp_types import DPGOp, WindowExInfo, XPGeom
from simless.libs.window import WindowManager
from XPPython3.xp_typing import (
    XPLMCursorStatus, XPLMFontID, XPLMMenuID, XPLMMouseStatus, XPLMWindowDecoration, XPLMWindowID,
    XPLMWindowLayer
)

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPGraphicsAPI:
    """DearPyGui-backed graphics subsystem mixin for FakeXP.

    This class owns the DearPyGui lifecycle and exposes:
      - An XPLMGraphics-like API surface (xp.* semantics)
      - A small, explicit set of graphics-owned DearPyGui helpers (dpg_*)
    """

    # ------------------------------------------------------------------
    # XPLMGraphics draw callbacks
    #
    # Registered via registerDrawCallback().
    # Stored as (callback, phase, wants_before).
    # Executed during draw_frame() to enqueue draw commands.
    # ------------------------------------------------------------------
    _draw_callbacks: List[tuple[Callable[[int, int], Any], int, int]]

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
    _screen_drawlist_front: Optional[str]  # Above all windows (optional)

    # Currently selected draw target for XPLMGraphics enqueue.
    # Switched temporarily while processing WindowEx draw callbacks.
    _active_drawlist: Optional[str]

    # ------------------------------------------------------------------
    # WindowEx bookkeeping
    #
    # Graphics-owned windows with independent drawlists and callbacks.
    # ------------------------------------------------------------------
    _current_window_ex: Optional[WindowExInfo]
    _keyboard_focus_window: Optional[XPLMWindowID]

    _menus: Dict[XPLMMenuID, Dict[str, Any]]
    _next_menu_id: int
    _menu_callbacks: Dict[XPLMMenuID, Callable]
    _root_plugins_menu: Optional[XPLMMenuID]

    window_manager: WindowManager

    @property
    def fake_xp(self) -> FakeXP:
        return cast("FakeXP", cast(object, self))

    def createWindowEx(
        self,
        left: int = 100,
        top: int = 200,
        right: int = 200,
        bottom: int = 100,
        visible: int = 0,
        draw: Optional[Callable[[XPLMWindowID, Any], None]] = None,
        click: Optional[
            Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
        ] = None,
        key: Optional[
            Callable[[XPLMWindowID, int, int, int, Any, int], int]
        ] = None,
        cursor: Optional[
            Callable[[XPLMWindowID, int, int, Any], XPLMCursorStatus]
        ] = None,
        wheel: Optional[
            Callable[[XPLMWindowID, int, int, int, int, Any], int]
        ] = None,
        refCon: Any = None,
        decoration: XPLMWindowDecoration = None,
        layer: XPLMWindowLayer = None,
        rightClick: Optional[
            Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
        ] = None,
    ) -> XPLMWindowID:
        if decoration is None:
            decoration = self.fake_xp.WindowDecorationRoundRectangle
        if layer is None:
            layer = self.fake_xp.WindowLayerFloatingWindows

        # --------------------------------------------------------------
        # Register FIRST — this creates the info object
        # --------------------------------------------------------------
        info = self.fake_xp.window_manager.register_windowex(
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            visible=bool(visible),
            decoration=decoration,
            layer=layer,
            draw_cb=draw,
            click_cb=click,
            right_click_cb=rightClick,
            key_cb=key,
            cursor_cb=cursor,
            wheel_cb=wheel,
            refcon=refCon,
        )

        # 2. Backend creation (DPG)
        dpg_geom = info.frame.to_dpg(self.fake_xp.dpg_get_viewport_client_height())

        self.fake_xp.enqueue_dpg(
            DPGOp.ADD_WINDOW,
            args=(),
            kwargs=dict(
                tag=info.dpg_tag,
                label=f"XPLMWindowEx {info.wid}",
                pos=(dpg_geom.x, dpg_geom.y),
                width=dpg_geom.width,
                height=dpg_geom.height,
                no_title_bar=False,
                no_resize=False,
                no_move=False,
                no_scrollbar=True,
                no_collapse=True,
                show=info.visible,
            ),
        )

        self.fake_xp.enqueue_dpg(
            DPGOp.ADD_DRAWLIST,
            args=(),
            kwargs=dict(
                tag=info.drawlist_tag,
                width=dpg_geom.width,
                height=dpg_geom.height,
                parent=info.dpg_tag,
            ),
        )

        return info.wid

    def destroyWindow(self, wid: XPLMWindowID) -> None:
        info = self.fake_xp.window_manager.get_info(wid)
        if info is None:
            return  # XP silently ignores invalid IDs

        # Destroy widgets first
        if info.widget_root:
            self.fake_xp.destroyWidget(info.widget_root)
            return

        # Remove from registry
        self.fake_xp.window_manager.destroy_window(wid)

        # Backend cleanup
        self.fake_xp.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.drawlist_tag,))
        self.fake_xp.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.dpg_tag,))

    def getWindowGeometry(self, wid: XPLMWindowID):
        info = self.fake_xp.window_manager.require_info(wid)
        return info.frame.left, info.frame.top, info.frame.right, info.frame.bottom

    def setWindowGeometry(self, wid, left, top, right, bottom):
        info = self.fake_xp.window_manager.require_info(wid)
        info.set_frame_from_xp(XPGeom(left, top, right, bottom))

    def getWindowRefCon(self, wid: XPLMWindowID):
        info = self.fake_xp.window_manager.require_info(wid)
        return info.refcon

    def setWindowRefCon(self, wid: XPLMWindowID, refCon):
        info = self.fake_xp.window_manager.require_info(wid)
        info.refcon = refCon

    def takeKeyboardFocus(self, wid: XPLMWindowID):
        self.fake_xp.window_manager.require_info(wid)
        self.fake_xp._keyboard_focus_window = wid

    def setWindowIsVisible(self, wid: XPLMWindowID, visible: int):
        info = self.fake_xp.window_manager.require_info(wid)
        info.visible = bool(visible)

        self.fake_xp.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(info.dpg_tag,),
            kwargs=dict(show=info.visible),
        )

    def getWindowIsVisible(self, wid: XPLMWindowID) -> int:
        info = self.fake_xp.window_manager.require_info(wid)
        return int(info.visible)
    # ----------------------------------------------------------------------
    # DRAW CALLBACK REGISTRATION (XP SEMANTICS)
    # ----------------------------------------------------------------------
    def registerDrawCallback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wantsBefore: int,
    ) -> None:
        self._draw_callbacks.append((cb, phase, wantsBefore))

    def unregisterDrawCallback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wantsBefore: int,
    ) -> None:
        self._draw_callbacks = [
            entry
            for entry in self._draw_callbacks
            if not (entry[0] is cb and entry[1] == phase and entry[2] == wantsBefore)
        ]

    # ----------------------------------------------------------------------
    # TEXT DRAWING (DEFERRED DPG COMMAND)
    # ----------------------------------------------------------------------
    def drawString(self, color, x, y, text, wordWrap, fontID) -> None:
        if self._active_drawlist is None:
            raise RuntimeError("drawString outside draw phase")

        win = self._current_window_ex
        if win is None:
            raise RuntimeError("drawString with no active window")

        # Authoritative XP frame geometry
        w_left = win.frame.left
        w_top = win.frame.top

        # XP → window-local DPG coordinates
        local_x = x - w_left
        local_y = w_top - y

        # Optional baseline correction (DPG draws from top-left of glyph box)
        local_y -= 12

        # Convert normalized XP color → 0–255 RGBA
        r = int(color[0] * 255)
        g = int(color[1] * 255)
        b = int(color[2] * 255)

        self.fake_xp.enqueue_dpg(
            DPGOp.DRAW_TEXT,
            target_drawlist=self._active_drawlist,
            args=((local_x, local_y), text),
            kwargs=dict(
                color=(r, g, b, 255),
                size=14,
            ),
        )

    def drawNumber(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        number: float,
        digits: int,
        decimals: int,
    ) -> None:
        fmt = f"{{:{digits}.{decimals}f}}"
        self.drawString(color, x, y, fmt.format(number), 0, 0)

    # ----------------------------------------------------------------------
    # GRAPHICS STATE (STUB)
    # ----------------------------------------------------------------------
    def setGraphicsState(
        self,
        fog: int,
        lighting: int,
        alpha: int,
        smooth: int,
        texUnits: int,
        texMode: int,
        depth: int,
    ) -> None:
        return

    # ----------------------------------------------------------------------
    # TEXTURE API (STUB)
    # ----------------------------------------------------------------------
    def generateTextureNumbers(self, count: int) -> List[int]:
        ids: List[int] = []
        for _ in range(count):
            tid = self._next_tex_id
            self._next_tex_id += 1
            self._textures[tid] = None
            ids.append(tid)
        return ids

    def bindTexture2d(self, textureID: int, unit: int) -> None:
        return

    def deleteTexture(self, textureID: int) -> None:
        self._textures.pop(textureID, None)

    # ----------------------------------------------------------------------
    # XP-STYLE PRIMITIVES (DEFERRED)
    # ----------------------------------------------------------------------
    def drawTranslucentDarkBox(self, left: int, top: int, right: int, bottom: int) -> None:
        if self._active_drawlist is None:
            raise RuntimeError("drawTranslucentDarkBox outside draw phase")

        win = self._current_window_ex
        if win is None:
            raise RuntimeError("drawTranslucentDarkBox with no active window")

        # Authoritative XP frame rectangle
        w_left = win.frame.left
        w_top = win.frame.top

        # XP → window-local coordinates (DPG local space)
        local_left = left - w_left
        local_top = w_top - top
        local_right = right - w_left
        local_bottom = w_top - bottom

        self.fake_xp.enqueue_dpg(
            DPGOp.DRAW_RECTANGLE,
            target_drawlist=self._active_drawlist,
            args=((local_left, local_top), (local_right, local_bottom)),
            kwargs=dict(
                fill=(0, 0, 0, 150),
                color=(0, 0, 0, 200),
                thickness=1,
            ),
        )

    def getScreenSize(self) -> Tuple[int, int]:
        return (
            self.fake_xp.dpg_get_viewport_client_height(),
            self.fake_xp.dpg_get_viewport_client_height(),
        )

    def getMouseLocation(self) -> Tuple[int, int]:
        x, y = self.fake_xp.dpg_get_mouse_pos()
        return int(x), int(y)

    def getFontDimensions(self, font_id: XPLMFontID) -> None | tuple[int, int, int]:
        # Basic, XP-authentic defaults
        if font_id == self.fake_xp.Font_Basic:
            return 8, 14, 3
        if font_id == self.fake_xp.Font_Proportional:
            return 7, 11, 2

        # fallback
        return 8, 14, 3

    # ================================================================
    # XPLMMenus API — strongly typed, XP-faithful, Plugins-root aware
    # ================================================================

    def _resolve_parent(self, parentMenuID: Optional[XPLMMenuID]) -> XPLMMenuID:
        """
        XP semantics:
          - None → Plugins menu
          - 0 → Plugins menu
          - otherwise → explicit parent
        """
        if parentMenuID is None or parentMenuID == XPLMMenuID(0):
            return self._root_plugins_menu
        return parentMenuID

    def createMenu(
        self,
        name: Optional[str] = None,
        parentMenuID: Optional[XPLMMenuID] = None,
        parentItem: Optional[int] = 0,
        handler: Optional[Callable[[Any, Any], None]] = None,
        refCon: Optional[Any] = None,
    ) -> Optional[XPLMMenuID]:

        parent = self._resolve_parent(parentMenuID)

        if parent not in self._menus:
            return None

        items = self._menus[parent]["items"]
        if parentItem < 0 or parentItem > len(items):
            return None

        mid = XPLMMenuID(self._next_menu_id)
        self._next_menu_id += 1

        # Create DPG tag for this menu
        dpg_tag = f"menu_{mid}"

        self._menus[mid] = {
            "name": name or "",
            "parent": parent,
            "parent_item": parentItem,
            "handler": handler,
            "refcon": refCon,
            "items": [],
            "dpg_tag": dpg_tag,  # ⭐ authoritative DPG tag
        }

        if handler:
            self._menu_callbacks[mid] = handler

        parent_tag = self._menus[parent]["dpg_tag"]

        self.fake_xp.enqueue_dpg(
            DPGOp.ADD_MENU,
            args=(),
            kwargs={
                "label": name or "",
                "parent": parent_tag,
                "tag": dpg_tag,
            },
        )

        return mid

    def appendMenuItem(
        self,
        menuID: Optional[XPLMMenuID] = None,
        name: str = "Item",
        refCon: Any = None,
    ) -> int:

        if menuID is None or menuID not in self._menus:
            return -1

        menu = self._menus[menuID]
        idx = len(menu["items"])
        parent_tag = menu["dpg_tag"]
        item_tag = f"{parent_tag}_{idx}"

        menu["items"].append(
            {
                "name": name,
                "refcon": refCon,
                "enabled": True,
                "checked": self.fake_xp.Menu_Unchecked,
                "separator": False,
                "command": None,
                "tag": item_tag
            }
        )

        self.fake_xp.enqueue_dpg(
            DPGOp.ADD_MENU_ITEM,
            args=(),
            kwargs={
                "label": name,
                "parent": parent_tag,
                "tag": item_tag,
            },
        )

        return idx

    def appendMenuItemWithCommand(
        self,
        menuID: Optional[XPLMMenuID] = None,
        name: str = "Command",
        commandRef: Any = None,
    ) -> int:

        if menuID is None or menuID not in self._menus:
            return -1

        menu = self._menus[menuID]
        idx = len(menu["items"])
        parent_tag = menu["dpg_tag"]
        item_tag = f"{parent_tag}_{idx}"

        menu["items"].append(
            {
                "name": name,
                "refcon": None,
                "enabled": True,
                "checked": self.fake_xp.Menu_Unchecked,
                "separator": False,
                "command": commandRef,
                "tag": item_tag
            }
        )

        self.fake_xp.enqueue_dpg(
            DPGOp.ADD_MENU_ITEM,
            args=(),
            kwargs={
                "label": name,
                "parent": parent_tag,
                "tag": item_tag,
            },
        )

        return idx

    def appendMenuSeparator(self, menuID: XPLMMenuID = None) -> Optional[int]:
        if menuID is None or menuID not in self._menus:
            return None

        menu = self._menus[menuID]
        idx = len(menu["items"])

        menu["items"].append(
            {
                "name": "",
                "refcon": None,
                "enabled": False,
                "checked": self.fake_xp.Menu_NoCheck,
                "separator": True,
                "command": None,
            }
        )

        parent_tag = menu["dpg_tag"]

        self.fake_xp.enqueue_dpg(
            DPGOp.ADD_MENU_SEPARATOR,
            args=(),
            kwargs={
                "parent": parent_tag,
            },
        )

        return idx

    def setMenuItemName(self, menuID, index, name):
        if menuID is None or menuID not in self._menus:
            return

        items = self._menus[menuID]["items"]
        if index < 0 or index >= len(items):
            return

        items[index]["name"] = name

        tag = f"{self._menus[menuID]['dpg_tag']}_{index}"

        self.fake_xp.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(tag,),
            kwargs={"label": name},
        )

    def checkMenuItem(self, menuID, index, checked=None):
        if checked is None:
            checked = self.fake_xp.Menu_Checked

        if menuID is None or menuID not in self._menus:
            return

        items = self._menus[menuID]["items"]
        if index < 0 or index >= len(items):
            return

        items[index]["checked"] = checked

        tag = f"{self._menus[menuID]['dpg_tag']}_{index}"

        self.fake_xp.enqueue_dpg(
            DPGOp.SET_MENU_ITEM_CHECKED,
            args=(tag,),
            kwargs={"check": (checked == self.fake_xp.Menu_Checked)},
        )

    def enableMenuItem(self, menuID, index, enabled=1):
        if menuID is None or menuID not in self._menus:
            return

        items = self._menus[menuID]["items"]
        if index < 0 or index >= len(items):
            return

        items[index]["enabled"] = bool(enabled)

        tag = f"{self._menus[menuID]['dpg_tag']}_{index}"

        self.fake_xp.enqueue_dpg(
            DPGOp.SET_MENU_ITEM_ENABLED,
            args=(tag,),
            kwargs={"enabled": bool(enabled)},
        )

    def removeMenuItem(self, menuID, index):
        if menuID is None or menuID not in self._menus:
            return

        items = self._menus[menuID]["items"]
        if index < 0 or index >= len(items):
            return

        del items[index]

        tag = f"{self._menus[menuID]['dpg_tag']}_{index}"

        self.fake_xp.enqueue_dpg(
            DPGOp.DELETE_ITEM,
            args=(tag,),
            kwargs={},
        )
