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
from simless.libs.fake_xp_types import WindowExInfo
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

    xp: FakeXPInterface  # established in FakeXP

    # ------------------------------------------------------------------
    # XPLMGraphics draw callbacks
    #
    # Stored as (callback, phase, wants_before)
    # callback signature: cb(phase: int, wants_before: int) -> Any
    # ------------------------------------------------------------------
    _draw_callbacks: List[tuple[Callable[[int, int], Any], int, int]]

    # ------------------------------------------------------------------
    # Texture bookkeeping (simless stub)
    # ------------------------------------------------------------------
    _next_tex_id: int
    _textures: Dict[int, Any]

    # ------------------------------------------------------------------
    # DearPyGui lifecycle state
    #
    # _context_ready:
    #   DPG context + viewport exist
    #
    # _layout_ready:
    #   First frame rendered; viewport geometry stable
    # ------------------------------------------------------------------
    _context_ready: bool
    _layout_ready: bool

    # ------------------------------------------------------------------
    # Global screen draw surfaces
    #
    # These are viewport-attached drawlists representing the X-Plane
    # screen, not any specific window.
    #
    # drawString(), drawLine(), drawBox(), etc. target _active_drawlist.
    # ------------------------------------------------------------------
    _screen_drawlist_back: Optional[int]  # Behind all windows
    _screen_drawlist_front: Optional[int]  # Above all windows (optional)

    # Currently active draw target for XPLMGraphics calls.
    # Temporarily switched when drawing WindowEx windows.
    _active_drawlist: Optional[int]

    _windows_ex: Dict[XPLMWindowID, WindowExInfo]
    _next_window_id: int
    _keyboard_focus_window: Optional[XPLMWindowID]

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
        """Create a modern XPLM window (graphics-owned, not a widget)."""

        if decoration is None:
            decoration = self.xp.WindowDecorationRoundRectangle
        if layer is None:
            layer = self.xp.WindowLayerFloatingWindows

        self._require_context()

        wid = XPLMWindowID(self._next_window_id)
        self._next_window_id += 1

        width = max(1, right - left)
        height = max(1, top - bottom)

        dpg_window_id = self.xp.dpg_add_window(
            label=f"XPLMWindowEx {wid}",
            pos=[left, bottom],
            width=width,
            height=height,
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_scrollbar=True,
            no_collapse=True,
            show=bool(visible),
        )

        drawlist_id = self.xp.dpg_add_drawlist(
            width=width,
            height=height,
            parent=dpg_window_id,
        )

        info = WindowExInfo(
            wid=wid,
            geometry=(left, top, right, bottom),  # XP screen-space geometry
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
            dpg_window_id=dpg_window_id,
            drawlist_id=drawlist_id,
        )

        self._windows_ex[wid] = info
        return wid

    def destroyWindow(self, wid: XPLMWindowID) -> None:
        """
        Destroy a graphics-owned XPLM WindowEx window.

        This removes the window from the graphics registry and deletes
        all associated DearPyGui objects. Safe to call multiple times.
        """
        self._require_context()

        info = self._windows_ex.pop(wid, None)
        if info is None:
            # XP tolerates destroying an already-destroyed window
            return

        # If this window is currently the active draw target, clear it
        if self._active_drawlist == info.drawlist_id:
            self._active_drawlist = None

        # Destroy DPG objects (drawlist first, then window)
        try:
            if self.xp.dpg_does_item_exist(info.drawlist_id):
                self.xp.dpg_delete_item(info.drawlist_id)
        except Exception:
            pass

        try:
            if self.xp.dpg_does_item_exist(info.dpg_window_id):
                self.xp.dpg_delete_item(info.dpg_window_id)
        except Exception:
            pass

    def getWindowGeometry(self, wid: XPLMWindowID) -> tuple[int, int, int, int]:
        """
        Return the geometry of a WindowEx window in XP screen coordinates.

        The returned tuple is (left, top, right, bottom), matching XPLM semantics.
        """
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
        """Set WindowEx geometry in XP screen coordinates (left, top, right, bottom)."""
        self._require_context()

        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        info.geometry = (left, top, right, bottom)

        width = max(1, right - left)
        height = max(1, top - bottom)

        # Keep backend in sync (DPG uses (x, y) with y as bottom)
        if self.xp.dpg_does_item_exist(info.dpg_window_id):
            self.xp.dpg_configure_item(
                info.dpg_window_id,
                pos=(left, bottom),
                width=width,
                height=height,
            )

        if self.xp.dpg_does_item_exist(info.drawlist_id):
            self.xp.dpg_configure_item(
                info.drawlist_id,
                width=width,
                height=height,
            )

    def getWindowRefCon(self, windowID: XPLMWindowID):
        """Return the refCon associated with a WindowEx window."""
        self._require_context()

        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        return info.refcon

    def setWindowRefCon(self, windowID: XPLMWindowID, refCon) -> None:
        """Set the refCon associated with a WindowEx window."""
        self._require_context()

        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        info.refcon = refCon

    def takeKeyboardFocus(self, windowID: XPLMWindowID) -> None:
        """
        Take keyboard focus for a WindowEx window.

        Simless: validate and record focus if you track it; otherwise accept silently.
        """
        self._require_context()

        if windowID not in self._windows_ex:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        # Optional: track focus for your input router
        self._keyboard_focus_window = windowID

    def setWindowIsVisible(self, windowID: XPLMWindowID, visible: int) -> None:
        self._require_context()

        info = self._windows_ex.get(windowID)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {windowID}")

        info.visible = bool(visible)

        if self.xp.dpg_does_item_exist(info.dpg_window_id):
            self.xp.dpg_configure_item(info.dpg_window_id, show=info.visible)

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
    # TEXT DRAWING (DPG DRAWLIST)
    # ----------------------------------------------------------------------
    def drawString(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        text: str,
        wordWrap: int,
        fontID: int,
    ) -> None:
        """
        Draw text to the active XPLMGraphics surface.

        This draws to the *current* draw target:
          - Global screen drawlist during normal draw callbacks
          - Window-local drawlist during createWindowEx draw callbacks

        This method is window-agnostic by design, matching XPLM semantics.
        """
        self._require_context()

        if self._active_drawlist is None:
            raise RuntimeError(
                "No active graphics drawlist (graphics root not initialized or draw phase not active)."
            )

        # Convert XP float color (0.0–1.0) to DPG RGBA (0–255)
        r = int(color[0] * 255)
        g = int(color[1] * 255)
        b = int(color[2] * 255)

        self.xp.dpg_draw_text(
            pos=(x, y),
            text=text,
            color=(r, g, b, 255),
            parent=self._active_drawlist,
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
    # SCREEN + MOUSE (XP API) — DPG AS SOURCE OF TRUTH
    # ----------------------------------------------------------------------
    def getScreenSize(self) -> Tuple[int, int]:
        self._require_context()
        self._require_layout()
        return self.xp.dpg_get_viewport_width(), self.xp.dpg_get_viewport_height()

    def getMouseLocation(self) -> Tuple[int, int]:
        self._require_context()
        self._require_layout()
        x, y = self.xp.dpg_get_mouse_pos()
        return int(x), int(y)
