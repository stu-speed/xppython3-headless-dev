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

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from simless.libs.fake_xp_interface import FakeXPInterface
from simless.libs.fake_xp_types import DPGOp, WindowExInfo
from XPPython3.xp_typing import (
    XPLMCursorStatus, XPLMFontID, XPLMMouseStatus, XPLMWindowDecoration, XPLMWindowID, XPLMWindowLayer
)

DPGCallback = Callable[[int | str, Any, Any], Any]


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
    _screen_drawlist_back: Optional[int]  # Behind all windows
    _screen_drawlist_front: Optional[int]  # Above all windows (optional)

    # Currently selected draw target for XPLMGraphics enqueue.
    # Switched temporarily while processing WindowEx draw callbacks.
    _active_drawlist: Optional[int]

    # ------------------------------------------------------------------
    # WindowEx bookkeeping
    #
    # Graphics-owned windows with independent drawlists and callbacks.
    # ------------------------------------------------------------------
    _windows_ex: Dict[XPLMWindowID, WindowExInfo]
    _current_window_ex: Optional[WindowExInfo]
    _next_window_id: int
    _keyboard_focus_window: Optional[XPLMWindowID]

    xp: FakeXPInterface  # established in FakeXP

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
            decoration = self.xp.WindowDecorationRoundRectangle
        if layer is None:
            layer = self.xp.WindowLayerFloatingWindows

        wid = XPLMWindowID(self._next_window_id)
        self._next_window_id += 1

        # --------------------------------------------------------------
        # 1) XP authoritative frame rect
        # --------------------------------------------------------------
        frame = (left, top, right, bottom)
        is_visible = bool(visible)

        width = max(1, right - left)
        height = max(1, top - bottom)

        # --------------------------------------------------------------
        # 3) Allocate backend IDs
        # --------------------------------------------------------------
        dpg_window_id = f"xplm_window_{wid}"
        drawlist_id = f"xplm_window_drawlist_{wid}"

        # --------------------------------------------------------------
        # 4) Enqueue backend window creation
        # --------------------------------------------------------------
        self.xp.enqueue_dpg(
            DPGOp.ADD_WINDOW,
            args=(),
            kwargs=dict(
                tag=dpg_window_id,
                label=f"XPLMWindowEx {wid}",
                pos=(0, 0),  # geometry applied later
                width=width,
                height=height,
                no_title_bar=False,
                no_resize=False,
                no_move=False,
                no_scrollbar=True,
                no_collapse=True,
                show=is_visible,
            ),
        )

        self.xp.enqueue_dpg(
            DPGOp.ADD_DRAWLIST,
            args=(),
            kwargs=dict(
                tag=drawlist_id,
                width=width,
                height=height,
                parent=dpg_window_id,
            ),
        )

        # --------------------------------------------------------------
        # 5) Construct WindowExInfo with BOTH rects
        # --------------------------------------------------------------
        info = WindowExInfo(
            wid=wid,
            frame=frame,
            client=frame,
            visible=is_visible,
            decoration=decoration,
            layer=layer,
            draw_cb=draw,
            click_cb=click,
            right_click_cb=rightClick,
            key_cb=key,
            cursor_cb=cursor,
            wheel_cb=wheel,
            refcon=refCon,
            dpg_window_id=dpg_window_id,
            drawlist_id=drawlist_id,
        )

        self._windows_ex[wid] = info
        return wid

    def destroyWindow(self, wid: XPLMWindowID) -> None:
        """
        Destroy a graphics-owned WindowEx window.

        XP-authentic behavior:
        - Destroy the DPG window (auto-deletes all child DPG items)
        - Destroy all widgets belonging to this WindowEx
        - Remove the WindowEx from the registry
        - Clear active drawlist if needed
        - Mark graphics as needing redraw
        """

        info = self.xp.get_windowex(wid)
        if info is None:
            # XP tolerates destroying an already-destroyed window
            return
        if info.widgets:
            self.xp.destroyWidget(info.widget_root)
            # destroyWidget will call this method again after cleanup
            return

        # --------------------------------------------------------------
        # 1. Remove the WindowEx record
        # --------------------------------------------------------------
        info = self._windows_ex.pop(wid, None)

        # --------------------------------------------------------------
        # 2. Clear active drawlist if this window was the target
        # --------------------------------------------------------------
        if self._active_drawlist == info.drawlist_id:
            self._active_drawlist = None

        # --------------------------------------------------------------
        # 4. Delete the DPG drawlist (if it exists)
        # --------------------------------------------------------------
        if info.drawlist_id is not None:
            self.xp.enqueue_dpg(
                DPGOp.DELETE_ITEM,
                args=(info.drawlist_id,),
            )

        # --------------------------------------------------------------
        # 5. Delete the DPG window (auto-deletes all children)
        # --------------------------------------------------------------
        if info.dpg_window_id is not None:
            self.xp.enqueue_dpg(
                DPGOp.DELETE_ITEM,
                args=(info.dpg_window_id,),
            )

    def getWindowGeometry(self, wid: XPLMWindowID) -> tuple[int, int, int, int]:
        info = self._windows_ex.get(wid)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {wid}")

        # XP authoritative frame rect
        return info.frame

    def setWindowGeometry(
        self,
        windowID: XPLMWindowID,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None:

        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        # Update XP authoritative frame rect
        info.frame = (left, top, right, bottom)
        info.dirty_xp_to_dpg = True

    def getWindowRefCon(self, windowID: XPLMWindowID):
        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        return info.refcon

    def setWindowRefCon(self, windowID: XPLMWindowID, refCon) -> None:
        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        info.refcon = refCon

    def takeKeyboardFocus(self, windowID: XPLMWindowID) -> None:
        if windowID not in self._windows_ex:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        self._keyboard_focus_window = windowID

    def setWindowIsVisible(self, windowID: XPLMWindowID, visible: int) -> None:
        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        info.visible = bool(visible)

        self.xp.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(info.dpg_window_id,),
            kwargs=dict(show=info.visible),
        )

    def getWindowIsVisible(self, windowID: XPLMWindowID) -> int:
        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

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
    def drawString(self, color, x, y, text, wordWrap, fontID):
        if self._active_drawlist is None:
            raise RuntimeError("drawString outside draw phase")

        win = self._current_window_ex
        left, top, right, bottom = win.frame  # authoritative XP frame rect

        # XP → window-local DPG coords
        local_x = x - left
        local_y = top - y  # XP origin at top-left, DPG at top-left

        # Optional baseline correction (DPG draws from top-left of glyph box)
        local_y -= 12

        r = int(color[0] * 255)
        g = int(color[1] * 255)
        b = int(color[2] * 255)

        self.xp.enqueue_dpg(
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
    def drawTranslucentDarkBox(self, left, top, right, bottom):
        if self._active_drawlist is None:
            raise RuntimeError("drawTranslucentDarkBox outside draw phase")

        win = self._current_window_ex
        w_left, w_top, w_right, w_bottom = win.frame  # authoritative XP frame rect

        # XP → window-local DPG coordinates
        local_left = left - w_left
        local_top = w_top - top
        local_right = right - w_left
        local_bottom = w_top - bottom

        self.xp.enqueue_dpg(
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
            self.xp.dpg_get_viewport_client_height(),
            self.xp.dpg_get_viewport_client_height(),
        )

    def getMouseLocation(self) -> Tuple[int, int]:
        x, y = self.xp.dpg_get_mouse_pos()
        return int(x), int(y)

    def getFontDimensions(self, font_id: XPLMFontID) -> None | tuple[int, int, int]:
        # Basic, XP-authentic defaults
        if font_id == self.xp.Font_Basic:
            return 8, 14, 3
        if font_id == self.xp.Font_Proportional:
            return 7, 11, 2
        if font_id == self.xp.Font_Large:
            return 10, 18, 4

        # fallback
        return 8, 14, 3
