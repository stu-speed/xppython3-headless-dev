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

from typing import Any, Callable, cast, List, Optional, Sequence, Tuple, TYPE_CHECKING

from simless.libs.graphics import GraphicsManager
from simless.libs.fake_xp_types import DPGOp, XPGeom
from XPPython3.xp_typing import (
    XPLMCursorStatus, XPLMFontID, XPLMMenuID, XPLMMouseStatus, XPLMWindowDecoration, XPLMWindowID,
    XPLMWindowLayer
)

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPGraphics:
    @property
    def fake_xp(self) -> FakeXP:
        return cast("FakeXP", cast(object, self))

    @property
    def gm(self) -> GraphicsManager:
        return self.fake_xp.graphics_manager

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
        dpg_geom = info.frame.to_dpg(self.gm.dpg_get_viewport_client_height())

        self.gm.enqueue_dpg(
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

        self.gm.enqueue_dpg(
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
        self.gm.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.drawlist_tag,))
        self.gm.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.dpg_tag,))

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

        self.gm.enqueue_dpg(
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
        self.gm.register_draw_callback(cb, phase, wantsBefore)

    def unregisterDrawCallback(
        self,
        cb: Callable[[int, int], Any],
        phase: int,
        wantsBefore: int,
    ) -> None:
        self.gm.unregister_draw_callback(cb, phase, wantsBefore)

    # ----------------------------------------------------------------------
    # TEXT DRAWING (DEFERRED DPG COMMAND)
    # ----------------------------------------------------------------------
    def drawString(self, color, x, y, text, wordWrap, fontID) -> None:
        gm = self.gm

        active = gm.get_active_drawlist()
        if active is None:
            raise RuntimeError("drawString outside draw phase")

        win = gm.get_current_window()
        if win is None:
            raise RuntimeError("drawString with no active window")

        # XP authoritative frame
        w_left = win.frame.left
        w_top = win.frame.top

        # XP → window-local DPG coordinates
        local_x = x - w_left
        local_y = w_top - y

        # Baseline correction
        local_y -= 12

        # Convert normalized XP color → 0–255 RGBA
        r = int(color[0] * 255)
        g = int(color[1] * 255)
        b = int(color[2] * 255)

        gm.enqueue_dpg(
            DPGOp.DRAW_TEXT,
            target_drawlist=active,
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
        gm = self.gm
        ids: List[int] = []
        for _ in range(count):
            tid = gm._next_tex_id
            gm._next_tex_id += 1
            gm._textures[tid] = None
            ids.append(tid)
        return ids

    def bindTexture2d(self, textureID: int, unit: int) -> None:
        return

    def deleteTexture(self, textureID: int) -> None:
        self.gm._textures.pop(textureID, None)

    # ----------------------------------------------------------------------
    # XP-STYLE PRIMITIVES (DEFERRED)
    # ----------------------------------------------------------------------
    def drawTranslucentDarkBox(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None:
        gm = self.gm

        active = gm.get_active_drawlist()
        if active is None:
            raise RuntimeError("drawTranslucentDarkBox outside draw phase")

        win = gm.get_current_window()
        if win is None:
            raise RuntimeError("drawTranslucentDarkBox with no active window")

        # XP authoritative frame
        w_left = win.frame.left
        w_top = win.frame.top

        # XP → window-local DPG coordinates
        local_left = left - w_left
        local_top = w_top - top
        local_right = right - w_left
        local_bottom = w_top - bottom

        gm.enqueue_dpg(
            DPGOp.DRAW_RECTANGLE,
            target_drawlist=active,
            args=((local_left, local_top), (local_right, local_bottom)),
            kwargs=dict(
                fill=(0, 0, 0, 150),
                color=(0, 0, 0, 200),
                thickness=1,
            ),
        )

    def getScreenSize(self) -> Tuple[int, int]:
        return (
            self.gm.dpg_get_viewport_client_height(),
            self.gm.dpg_get_viewport_client_height(),
        )

    def getMouseLocation(self) -> Tuple[int, int]:
        x, y = self.gm.dpg_get_mouse_pos()
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
    # XPLMMenus API — XP-faithful, strongly typed, GM-backed
    # ================================================================

    def _resolve_parent(self, parentMenuID: Optional[XPLMMenuID]) -> XPLMMenuID:
        """
        XP semantics:
          - None → Plugins menu
          - 0 → Plugins menu
          - otherwise → explicit parent
        """
        if parentMenuID is None or parentMenuID == XPLMMenuID(0):
            return self.gm.get_root_plugins_menu()
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

        # Validate parent menu
        if not self.gm.has_menu(parent):
            return None

        items = self.gm.get_menu_items(parent)
        if parentItem < 0 or parentItem > len(items):
            return None

        # Allocate new menu ID
        mid = self.gm.allocate_menu_id()

        # Create authoritative DPG tag
        dpg_tag = f"menu_{mid}"

        # Register menu in GM
        self.gm.create_menu_record(
            menu_id=mid,
            name=name or "",
            parent=parent,
            parent_item=parentItem,
            handler=handler,
            refcon=refCon,
            dpg_tag=dpg_tag,
        )

        parent_tag = self.gm.get_menu_parent_tag(parent)

        # Enqueue DPG creation
        self.gm.enqueue_dpg(
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

        gm = self.gm

        if menuID is None or not gm.has_menu(menuID):
            return -1

        parent_tag = gm.get_menu_parent_tag(menuID)
        items = gm.get_menu_items(menuID)
        idx = len(items)
        item_tag = f"{parent_tag}_{idx}"

        gm.append_menu_item_record(
            menu_id=menuID,
            name=name,
            refcon=refCon,
            checked=self.fake_xp.Menu_Unchecked,
            enabled=True,
            separator=False,
            command=None,
            tag=item_tag,
        )

        gm.enqueue_dpg(
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

        if menuID is None or not self.gm.has_menu(menuID):
            return -1

        parent_tag = self.gm.get_menu_parent_tag(menuID)
        items = self.gm.get_menu_items(menuID)
        idx = len(items)
        item_tag = f"{parent_tag}_{idx}"

        self.gm.append_menu_item_record(
            menu_id=menuID,
            name=name,
            refcon=None,
            checked=self.fake_xp.Menu_Unchecked,
            enabled=True,
            separator=False,
            command=commandRef,
            tag=item_tag,
        )

        self.gm.enqueue_dpg(
            DPGOp.ADD_MENU_ITEM,
            args=(),
            kwargs={
                "label": name,
                "parent": parent_tag,
                "tag": item_tag,
            },
        )

        return idx

    def appendMenuSeparator(self, menuID: Optional[XPLMMenuID] = None) -> Optional[int]:
        if menuID is None or not self.gm.has_menu(menuID):
            return None

        items = self.gm.get_menu_items(menuID)
        if items is None:
            return None

        idx: int = len(items)
        parent_tag: str = self.gm.get_menu_parent_tag(menuID)

        # Insert separator record
        self.gm.append_menu_item_record(
            menu_id=menuID,
            name="",
            refcon=None,
            enabled=False,
            checked=self.fake_xp.Menu_NoCheck,
            separator=True,
            command=None,
            tag="",  # separators have no tag
        )

        # Enqueue DPG separator
        self.gm.enqueue_dpg(
            DPGOp.ADD_MENU_SEPARATOR,
            args=(),
            kwargs={"parent": parent_tag},
        )

        return idx

    def setMenuItemName(self, menuID: Optional[XPLMMenuID], index: int, name: str) -> None:
        if menuID is None or not self.gm.has_menu(menuID):
            return

        items = self.gm.get_menu_items(menuID)
        if items is None or index < 0 or index >= len(items):
            return

        self.gm.set_menu_item_name(menuID, index, name)

        tag: str = f"{self.gm.get_menu_parent_tag(menuID)}_{index}"

        self.gm.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(tag,),
            kwargs={"label": name},
        )

    def checkMenuItem(
        self,
        menuID: Optional[XPLMMenuID],
        index: int,
        checked: Optional[int] = None,
    ) -> None:
        if checked is None:
            checked = self.fake_xp.Menu_Checked

        if menuID is None or not self.gm.has_menu(menuID):
            return

        items = self.gm.get_menu_items(menuID)
        if items is None or index < 0 or index >= len(items):
            return

        self.gm.set_menu_item_checked(menuID, index, checked)

        tag: str = f"{self.gm.get_menu_parent_tag(menuID)}_{index}"

        self.gm.enqueue_dpg(
            DPGOp.SET_MENU_ITEM_CHECKED,
            args=(tag,),
            kwargs={"check": (checked == self.fake_xp.Menu_Checked)},
        )

    def enableMenuItem(
        self,
        menuID: Optional[XPLMMenuID],
        index: int,
        enabled: int = 1,
    ) -> None:
        if menuID is None or not self.gm.has_menu(menuID):
            return

        items = self.gm.get_menu_items(menuID)
        if items is None or index < 0 or index >= len(items):
            return

        self.gm.set_menu_item_enabled(menuID, index, bool(enabled))

        tag: str = f"{self.gm.get_menu_parent_tag(menuID)}_{index}"

        self.gm.enqueue_dpg(
            DPGOp.SET_MENU_ITEM_ENABLED,
            args=(tag,),
            kwargs={"enabled": bool(enabled)},
        )

    def removeMenuItem(self, menuID: Optional[XPLMMenuID], index: int) -> None:
        if menuID is None or not self.gm.has_menu(menuID):
            return

        items = self.gm.get_menu_items(menuID)
        if items is None or index < 0 or index >= len(items):
            return

        self.gm.remove_menu_item(menuID, index)

        tag: str = f"{self.gm.get_menu_parent_tag(menuID)}_{index}"

        self.gm.enqueue_dpg(
            DPGOp.DELETE_ITEM,
            args=(tag,),
            kwargs={},
        )
