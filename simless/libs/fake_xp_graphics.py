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

from typing import Any, Callable, List, Optional, Sequence, TYPE_CHECKING, Tuple, cast

from simless.libs.fake_xp_types import DPGOp, XPGeom
from simless.libs.graphics import GraphicsManager
from xp_typing import (XPLMCursorStatus, XPLMFontID, XPLMMouseStatus,
                       XPLMWindowDecoration, XPLMWindowID, XPLMWindowLayer)

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPGraphics:
    @property
    def fake_xp(self) -> FakeXP:
        return cast(FakeXP, cast(object, self))

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
            decoration: Optional[XPLMWindowDecoration] = None,
            layer: Optional[XPLMWindowLayer] = None,
            rightClick: Optional[
                Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
            ] = None,
    ) -> XPLMWindowID | int:
        if decoration is None:
            decoration = self.fake_xp.WindowDecorationRoundRectangle
        if layer is None:
            layer = self.fake_xp.WindowLayerFloatingWindows

        # --------------------------------------------------------------
        # Register FIRST — this creates the info object
        # --------------------------------------------------------------
        info = self.fake_xp.window_manager.create_window(
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

        return info.wid

    def destroyWindow(self, wid: XPLMWindowID) -> None:
        info = self.fake_xp.window_manager.require_info(wid)

        # Destroy widgets first
        root = info.widget_root
        if root is not None:
            self.fake_xp.destroyWidget(root)
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
            self.gm.dpg_get_viewport_client_width(),
            self.gm.dpg_get_viewport_client_height(),
        )

    def getMouseLocation(self) -> Tuple[int, int]:
        x, y = self.gm.dpg_get_mouse_pos()
        return int(x), int(y)

    def getFontDimensions(self, font_id: XPLMFontID) -> tuple[int, int, int]:
        # Basic, XP-authentic defaults
        digits_only = 0
        s = self.gm.dpg_get_text_size("L")
        if s is None:
            if font_id == self.fake_xp.Font_Proportional:
                return 6, 12, digits_only  # dpg not ready
            return 7, 13, digits_only  # dpg not ready
        return int(s[0]), int(s[1]), digits_only

    def measureString(self, font_id: XPLMFontID, string: str) -> float:
        # Basic, XP-authentic defaults
        digits_only = 0
        s = self.gm.dpg_get_text_size(string)
        if s is None:
            if font_id == self.fake_xp.Font_Proportional:
                return 6 * len(string)  # dpg not ready
            return 7 * len(string)  # dpg not ready
        return s[0]
