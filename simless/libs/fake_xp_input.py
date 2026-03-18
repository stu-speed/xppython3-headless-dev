# ===========================================================================
# FakeXPInput — input routing subsystem mixin for FakeXP
#
# ROLE
#   Provide a minimal, deterministic, XPLM-style input façade for simless
#   execution. This subsystem owns the input event queue and routes events
#   to WindowEx callbacks using XP-semantic hit-testing, capture, and
#   keyboard-focus rules.
#
# API INVARIANTS
#   - Must match the observable behavior of XPLM input routing.
#   - Must not infer semantics or reinterpret plugin intent.
#   - Must not mutate SDK-shaped objects.
#   - All routing decisions must be deterministic and derived solely
#     from internal state (frame/client rects, capture, focus).
#
# LIFETIME INVARIANTS
#   - The DearPyGui context and viewport are created before plugin enable
#     and remain valid for the lifetime of FakeXP.
#   - Therefore, all input dispatch is always legal; no context gating or
#     deferred initialization is required.
#   - This subsystem is backend-agnostic: it never imports or touches DPG.
#     It consumes only normalized EventInfo objects from FakeXP.
#
# INPUT MODEL
#   - Mouse capture follows XP semantics: capture is set only when a
#     MouseDown is consumed, and released on MouseUp.
#   - Keyboard focus follows mouse capture: focus moves to the window
#     that consumes MouseDown.
#   - Hit-testing uses authoritative XP geometry (frame/client rects)
#     maintained by the graphics subsystem.
#   - Input routing is strictly:
#         Backend → FakeXPInput → WindowEx callbacks → Widgets
#
# PURPOSE
#   Provide a contributor-proof, deterministic input subsystem that
#   behaves like X-Plane’s XPLM input layer while remaining simple
#   enough for simless GUI testing.
# ===========================================================================

from __future__ import annotations

from typing import Any, Dict, List, Optional

from simless.libs.fake_xp_interface import FakeXPInterface
from simless.libs.fake_xp_types import EventInfo, EventKind, WindowExInfo
from XPPython3.xp_typing import (
    XPLMCursorStatus,
    XPLMMouseStatus,
    XPLMWindowID,
)


class FakeXPInput:
    """Input routing subsystem mixin for FakeXP."""

    xp: FakeXPInterface  # established in FakeXP

    # ------------------------------------------------------------------
    # WindowEx authoritative storage (owned by graphics subsystem)
    # ------------------------------------------------------------------
    _windows_ex: Dict[XPLMWindowID, WindowExInfo]

    # ------------------------------------------------------------------
    # Input state
    # ------------------------------------------------------------------
    _keyboard_focus_window: Optional[XPLMWindowID]
    _input_events: List[EventInfo]
    _mouse_capture_window: Optional[XPLMWindowID]
    _mouse_button_down: bool

    # ------------------------------------------------------------------
    # INITIALIZATION
    # ------------------------------------------------------------------
    def _init_input(self) -> None:
        """Initialize internal input state. Called by FakeXP during construction."""
        self._keyboard_focus_window = None
        self._input_events = []
        self._mouse_capture_window = None
        self._mouse_button_down = False

    # ------------------------------------------------------------------
    # INPUT QUEUE (engine-owned)
    # ------------------------------------------------------------------
    def queue_input_event(self, event: EventInfo) -> None:
        """Enqueue a normalized EventInfo object.

        Called by graphics/backend adapters only.
        """
        self._input_events.append(event)

    def drain_input_events(self) -> List[EventInfo]:
        """
        Return and clear all pending input events for this frame.
        The caller must check geometry_not_ready before processing.
        """
        events = self._input_events
        self._input_events = []
        return events

    # ------------------------------------------------------------------
    # GEOMETRY HELPERS
    # ------------------------------------------------------------------
    @staticmethod
    def _point_in_rect(x: int, y: int, rect: tuple[int, int, int, int]) -> bool:
        left, top, right, bottom = rect
        return (left <= x < right) and (bottom <= y < top)

    # ------------------------------------------------------------------
    # WINDOWEX ORDERING / PICKING
    # ------------------------------------------------------------------
    def _iter_window_ex_top_to_bottom(self):
        """Topmost-first ordering: higher layer, then higher wid."""
        return sorted(
            self._windows_ex.values(),
            key=lambda w: (w.layer, w.wid),
            reverse=True,
        )

    def _pick_window_ex_at(self, xp_x: int, xp_y: int) -> Optional[WindowExInfo]:
        for info in self._iter_window_ex_top_to_bottom():
            if info.visible and self._is_inside_frame(info, xp_x, xp_y):
                return info
        return None

    def _is_inside_client(self, info: WindowExInfo, xp_x: int, xp_y: int):
        return (info.client_left <= xp_x <= info.client_right) and (info.client_bottom <= xp_y <= info.client_top)

    def _is_inside_frame(self, info: WindowExInfo, xp_x: int, xp_y: int) -> bool:
        return (info.left <= xp_x <= info.right) and (info.bottom <= xp_y <= info.top)

    # ------------------------------------------------------------------
    # DISPATCH HELPERS (engine-invoked only)
    # ------------------------------------------------------------------
    def _dispatch_window_click(
        self,
        windowID: XPLMWindowID,
        xp_x: int,
        xp_y: int,
        mouseStatus: XPLMMouseStatus,
        right: bool = False,
    ) -> int:
        info = self._windows_ex.get(windowID)
        if info is None:
            return 0

        if not self._is_inside_client(info, xp_x, xp_y):
            return 0

        cb = info.right_click_cb if right else info.click_cb
        if cb is None:
            return 0

        return int(cb(windowID, xp_x, xp_y, mouseStatus, info.refcon))

    def _dispatch_window_key(
        self,
        windowID: XPLMWindowID,
        key: int,
        flags: int,
        vKey: int,
        losingFocus: int,
    ) -> int:
        info = self._windows_ex.get(windowID)
        if info is None or info.key_cb is None:
            return 0

        return int(
            info.key_cb(
                windowID,
                key,
                flags,
                vKey,
                info.refcon,
                losingFocus,
            )
        )

    def _dispatch_window_wheel(
        self,
        windowID: XPLMWindowID,
        xp_x: int,
        xp_y: int,
        wheel: int,
        clicks: int,
    ) -> int:
        info = self._windows_ex.get(windowID)
        if info is None or info.wheel_cb is None:
            return 0

        return int(info.wheel_cb(windowID, xp_x, xp_y, wheel, clicks, info.refcon))

    def _dispatch_window_cursor(
        self,
        windowID: XPLMWindowID,
        xp_x: int,
        xp_y: int,
    ) -> XPLMCursorStatus:
        info = self._windows_ex.get(windowID)
        if info is None or info.cursor_cb is None:
            return self.xp.CursorDefault

        return info.cursor_cb(windowID, xp_x, xp_y, info.refcon)

    # ------------------------------------------------------------------
    # SINGLE RUNNER ENTRY POINT (typed)
    # ------------------------------------------------------------------
    def process_event_info(self, event: EventInfo) -> Any:
        if event.kind is EventKind.MOUSE_BUTTON:
            if event.state is None:
                raise RuntimeError("MOUSE_BUTTON requires state")

            mouse_status = (
                self.xp.MouseDown if event.state == "down" else self.xp.MouseUp
            )

            return self._handle_mouse_button(
                xp_x=event.xp_x,
                xp_y=event.xp_y,
                mouseStatus=mouse_status,
                right=event.right,
            )

        if event.kind is EventKind.MOUSE_WHEEL:
            if event.wheel is None or event.clicks is None:
                raise RuntimeError("MOUSE_WHEEL requires wheel, clicks")

            return self._handle_mouse_wheel(
                xp_x=event.xp_x,
                xp_y=event.xp_y,
                wheel=event.wheel,
                clicks=event.clicks,
            )

        if event.kind is EventKind.CURSOR:
            return self._handle_cursor_query(event.xp_x, event.xp_y)

        if event.kind is EventKind.KEY:
            if event.key is None or event.flags is None or event.vKey is None:
                raise RuntimeError("KEY requires key, flags, vKey")

            return self._handle_key(
                key=event.key,
                flags=event.flags,
                vKey=event.vKey,
            )

        raise ValueError(f"Unhandled EventKind: {event.kind}")

    # ------------------------------------------------------------------
    # ROUTERS
    # ------------------------------------------------------------------
    def _handle_cursor_query(self, xp_x: int, xp_y: int) -> XPLMCursorStatus:
        if self._mouse_capture_window is not None:
            info = self._windows_ex.get(self._mouse_capture_window)
        else:
            info = self._pick_window_ex_at(xp_x, xp_y)

        if info is None:
            return self.xp.CursorDefault

        return self._dispatch_window_cursor(info.wid, xp_x, xp_y)

    def _handle_mouse_button(
        self,
        xp_x: int,
        xp_y: int,
        mouseStatus: XPLMMouseStatus,
        right: bool,
    ) -> int:

        # ------------------------------------------------------------
        # 1) Debounce MouseDown
        # ------------------------------------------------------------
        if mouseStatus == self.xp.MouseDown:
            if self._mouse_button_down:
                return 0
            self._mouse_button_down = True

        elif mouseStatus == self.xp.MouseUp:
            self._mouse_button_down = False

        # ------------------------------------------------------------
        # 2) Determine target window
        #    Capture bypasses hit-testing entirely
        # ------------------------------------------------------------
        if self._mouse_capture_window is not None:
            info = self._windows_ex.get(self._mouse_capture_window)
        else:
            info = self._pick_window_ex_at(xp_x, xp_y)

        if info is None:
            return 0

        # ------------------------------------------------------------
        # 3) Dispatch click callback
        # ------------------------------------------------------------
        consumed = self._dispatch_window_click(
            windowID=info.wid,
            xp_x=xp_x,
            xp_y=xp_y,
            mouseStatus=mouseStatus,
            right=right,
        )

        # ------------------------------------------------------------
        # 4) Capture on MouseDown
        # ------------------------------------------------------------
        if consumed and mouseStatus == self.xp.MouseDown:
            self._mouse_capture_window = info.wid
            self._keyboard_focus_window = info.wid

        # ------------------------------------------------------------
        # 5) Release capture AFTER dispatch
        # ------------------------------------------------------------
        if mouseStatus == self.xp.MouseUp:
            if self._mouse_capture_window == info.wid:
                self._mouse_capture_window = None

        return consumed

    def _handle_mouse_wheel(
        self,
        xp_x: int,
        xp_y: int,
        wheel: int,
        clicks: int,
    ) -> int:
        info = self._pick_window_ex_at(xp_x, xp_y)
        if info is None:
            return 0

        return self._dispatch_window_wheel(
            windowID=info.wid,
            xp_x=xp_x,
            xp_y=xp_y,
            wheel=wheel,
            clicks=clicks,
        )

    def _handle_key(self, key: int, flags: int, vKey: int) -> int:
        if self._keyboard_focus_window is None:
            return 0

        return self._dispatch_window_key(
            windowID=self._keyboard_focus_window,
            key=key,
            flags=flags,
            vKey=vKey,
            losingFocus=0,
        )

    # ------------------------------------------------------------------
    # FOCUS CONTROL
    # ------------------------------------------------------------------
    def clear_keyboard_focus(self) -> None:
        """Explicitly clear keyboard focus."""
        self._keyboard_focus_window = None
