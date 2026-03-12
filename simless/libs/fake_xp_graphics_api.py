# simless/libs/fake_xp_graphics_api.py
# ===========================================================================
# FakeXPGraphics — DearPyGui-backed graphics subsystem mixin for FakeXP
#
# ROLE
#   Provide a minimal, deterministic, XPLMGraphics-like façade for simless
#   execution. This subsystem mirrors the public xp graphics API surface
#   without inference, layout logic, or hidden state.
#
# CORE INVARIANTS
#   - Must match the production xp.* graphics API contract (xp.pyi).
#   - Must not infer semantics or perform validation.
#   - Must not mutate SDK-shaped objects.
#   - Must return deterministic values based solely on internal storage.
#
# LIFECYCLE INVARIANTS
#   - context_ready gates legality: any self.xp.dpg_* call requires context_ready.
#   - layout_ready gates correctness: any geometry/layout-dependent operation
#     requires layout_ready (first DPG frame rendered).
#   - Violations raise immediately; nothing fails silently.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from simless.libs.fake_xp_interface import FakeXPInterface
from simless.libs.fake_xp_types import DPGOp, WindowExInfo
from XPPython3.xp_typing import XPLMCursorStatus, XPLMMouseStatus, XPLMWindowDecoration, XPLMWindowID, XPLMWindowLayer

DPGCallback = Callable[[int | str, Any, Any], Any]


class FakeXPGraphicsAPI:
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
    # DearPyGui lifecycle state
    #
    # _context_ready:
    #   DPG context + viewport have been created.
    #
    # _layout_ready:
    #   At least one frame rendered; viewport geometry is stable.
    # ------------------------------------------------------------------
    _context_ready: bool
    _layout_ready: bool

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

    # ----------------------------------------------------------------------
    # INTERNAL GUARDS
    # ----------------------------------------------------------------------
    def _require_context(self) -> None:
        """Raise if any DPG call is attempted before context initialization."""
        if not self._context_ready:
            raise RuntimeError(
                "DearPyGui context not ready. Call init_graphics_root() before any dpg_* helper or DPG-backed XP API."
            )

    def _require_layout(self) -> None:
        """Raise if geometry/layout-dependent work is attempted too early."""
        if not self._layout_ready:
            raise RuntimeError(
                "DearPyGui layout not ready. Wait until after the first render_dearpygui_frame() before geometry/layout-dependent operations."
            )

    def _require_running(self) -> None:
        """Raise if DPG is no longer running (viewport closed / shutdown)."""
        self._require_context()
        if not self.xp.dpg_is_dearpygui_running():
            raise RuntimeError("DearPyGui is not running (viewport closed or shutdown).")

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
        """Create a graphics-owned XPLM WindowEx window."""

        if decoration is None:
            decoration = self.xp.WindowDecorationRoundRectangle
        if layer is None:
            layer = self.xp.WindowLayerFloatingWindows

        wid = XPLMWindowID(self._next_window_id)
        self._next_window_id += 1

        # XP-authoritative geometry
        geometry = (left, top, right, bottom)
        is_visible = bool(visible)

        width = max(1, right - left)
        height = max(1, top - bottom)

        # Allocate backend IDs deterministically
        dpg_window_id = f"xplm_window_{wid}"
        drawlist_id = f"xplm_window_drawlist_{wid}"

        # Enqueue backend window creation (canvas-style window)
        self.xp.enqueue_dpg(
            DPGOp.ADD_WINDOW,
            args=(),
            kwargs=dict(
                tag=dpg_window_id,
                label=f"XPLMWindowEx {wid}",
                pos=(0, 0),  # no applied geometry
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

        # Enqueue window-local drawlist
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

        info = WindowExInfo(
            wid=wid,
            geometry=geometry,
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
            geom_applied=False,
        )

        self._windows_ex[wid] = info
        return wid

    def destroyWindow(self, wid: XPLMWindowID) -> None:
        """Destroy a graphics-owned WindowEx window."""

        info = self._windows_ex.pop(wid, None)
        if info is None:
            return

        if self._active_drawlist == info.drawlist_id:
            self._active_drawlist = None

        self.xp.enqueue_dpg(
            DPGOp.DELETE_ITEM,
            args=(info.drawlist_id,),
        )

        self.xp.enqueue_dpg(
            DPGOp.DELETE_ITEM,
            args=(info.dpg_window_id,),
        )

    def getWindowGeometry(self, wid: XPLMWindowID) -> tuple[int, int, int, int]:
        self._require_context()

        info = self._windows_ex.get(wid)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {wid}")

        return info.geometry

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

        info.geometry = (left, top, right, bottom)

        width = max(1, right - left)
        height = max(1, top - bottom)

        self.xp.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(info.dpg_window_id,),
            kwargs=dict(
                pos=(left, bottom),
                width=width,
                height=height,
            ),
        )

        self.xp.enqueue_dpg(
            DPGOp.CONFIGURE_ITEM,
            args=(info.drawlist_id,),
            kwargs=dict(
                width=width,
                height=height,
            ),
        )

    def getWindowRefCon(self, windowID: XPLMWindowID):
        self._require_context()

        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        return info.refcon

    def setWindowRefCon(self, windowID: XPLMWindowID, refCon) -> None:
        self._require_context()

        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        info.refcon = refCon

    def takeKeyboardFocus(self, windowID: XPLMWindowID) -> None:
        self._require_context()

        if windowID not in self._windows_ex:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        self._keyboard_focus_window = windowID

    def setWindowIsVisible(self, windowID: XPLMWindowID, visible: int) -> None:
        self._require_context()

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
        self._require_context()

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
        left, top, right, bottom = win.geometry

        local_x = x - left
        local_y = (top - y) - 12  # baseline correction

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
        w_left, w_top, w_right, w_bottom = win.geometry

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

    # ----------------------------------------------------------------------
    # SCREEN + MOUSE (XP API) — IMMEDIATE QUERIES
    # ----------------------------------------------------------------------
    def getScreenSize(self) -> Tuple[int, int]:
        self._require_context()
        self._require_layout()
        return (
            self.xp.dpg_get_viewport_client_height(),
            self.xp.dpg_get_viewport_client_height(),
        )

    def getMouseLocation(self) -> Tuple[int, int]:
        self._require_context()
        self._require_layout()
        x, y = self.xp.dpg_get_mouse_pos()
        return int(x), int(y)
