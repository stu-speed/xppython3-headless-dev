# ===========================================================================
# FakeXPInput — input routing subsystem mixin for FakeXP
#
# ROLE
#   Provide a minimal, deterministic, XPLM-style input façade for simless
#   execution. This subsystem owns the input event queue and routes events
#   to WindowEx callbacks via XP-semantic hit-testing and focus rules.
#
# CORE INVARIANTS
#   - Must not infer semantics or perform validation beyond lifecycle gates.
#   - Must not mutate SDK-shaped objects.
#   - Must return deterministic values based solely on internal storage.
#
# LIFECYCLE INVARIANTS
#   - context_ready gates legality: any dispatch requires context_ready.
#   - layout_ready gates correctness: any geometry-dependent operation
#     requires layout_ready (first frame rendered).
#   - Violations raise immediately; nothing fails silently.
#
# SIMLESS RULES
#   - Backend-agnostic: no DearPyGui imports.
#   - Rendering decides visibility; input decides interactivity.
#   - Callbacks are engine-invoked only; plugins never call helpers.
# ===========================================================================

from __future__ import annotations

from typing import Dict, Optional, Any, List

from simless.libs.fake_xp_interface import FakeXPInterface
from simless.libs.fake_xp_types import WindowExInfo, EventInfo, EventKind

from XPPython3.xp_typing import (
    XPLMCursorStatus,
    XPLMMouseStatus,
    XPLMWindowID,
)


class FakeXPInput:
    """Input routing subsystem mixin for FakeXP."""

    xp: FakeXPInterface  # established in FakeXP

    # ------------------------------------------------------------------
    # Host-provided lifecycle gates (owned by graphics subsystem)
    # ------------------------------------------------------------------
    _context_ready: bool
    _layout_ready: bool

    def _require_context(self) -> None:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------
    # WindowEx authoritative storage (owned by graphics subsystem)
    # ------------------------------------------------------------------
    _windows_ex: Dict[XPLMWindowID, WindowExInfo]

    # ------------------------------------------------------------------
    # Input state
    # ------------------------------------------------------------------
    _keyboard_focus_window: Optional[XPLMWindowID]
    _input_events: List[EventInfo]

    public_api_names = [
        "queue_input_event",
        "drain_input_events",
        "process_event_info",
        "clear_keyboard_focus",
    ]

    # ------------------------------------------------------------------
    # INITIALIZATION
    # ------------------------------------------------------------------
    def _init_input(self) -> None:
        """Initialize internal input state. Called by FakeXP during construction."""
        self._keyboard_focus_window = None
        self._input_events = []

    # ------------------------------------------------------------------
    # INPUT QUEUE (engine-owned)
    # ------------------------------------------------------------------
    def queue_input_event(self, event: EventInfo) -> None:
        """Enqueue a normalized EventInfo object.

        Called by graphics/backend adapters only.
        """
        self._input_events.append(event)

    def drain_input_events(self) -> List[EventInfo]:
        """Return and clear all pending input events for this frame."""
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

    def _pick_window_ex_at(self, x: int, y: int) -> Optional[WindowExInfo]:
        for info in self._iter_window_ex_top_to_bottom():
            if not info.visible:
                continue
            if self._point_in_rect(x, y, info.geometry):
                return info
        return None

    # ------------------------------------------------------------------
    # DISPATCH HELPERS (engine-invoked only)
    # ------------------------------------------------------------------
    def _dispatch_window_click(
        self,
        windowID: XPLMWindowID,
        x: int,
        y: int,
        mouseStatus: XPLMMouseStatus,
        right: bool = False,
    ) -> int:
        info = self._windows_ex.get(windowID)
        if info is None:
            return 0

        cb = info.right_click_cb if right else info.click_cb
        if cb is None:
            return 0

        return int(cb(windowID, x, y, mouseStatus, info.refcon))

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
        x: int,
        y: int,
        wheel: int,
        clicks: int,
    ) -> int:
        info = self._windows_ex.get(windowID)
        if info is None or info.wheel_cb is None:
            return 0

        return int(info.wheel_cb(windowID, x, y, wheel, clicks, info.refcon))

    def _dispatch_window_cursor(
        self,
        windowID: XPLMWindowID,
        x: int,
        y: int,
    ) -> XPLMCursorStatus:
        info = self._windows_ex.get(windowID)
        if info is None or info.cursor_cb is None:
            return self.xp.CursorDefault

        return info.cursor_cb(windowID, x, y, info.refcon)

    # ------------------------------------------------------------------
    # SINGLE RUNNER ENTRY POINT (typed)
    # ------------------------------------------------------------------
    def process_event_info(self, event: EventInfo) -> Any:
        """Process one normalized EventInfo object."""
        self._require_context()
        if not self._layout_ready:
            raise RuntimeError("Input processing requires layout_ready")

        kind = event.kind

        if kind is EventKind.MOUSE_BUTTON:
            if event.x is None or event.y is None or event.state is None:
                raise RuntimeError("MOUSE_BUTTON requires x, y, state")

            mouse_status = (
                self.xp.MouseDown if event.state == "down" else self.xp.MouseUp
            )

            return self._handle_mouse_button(
                x=event.x,
                y=event.y,
                mouseStatus=mouse_status,
                right=event.right,
            )

        if kind is EventKind.MOUSE_WHEEL:
            if (
                event.x is None
                or event.y is None
                or event.wheel is None
                or event.clicks is None
            ):
                raise RuntimeError("MOUSE_WHEEL requires x, y, wheel, clicks")

            return self._handle_mouse_wheel(
                x=event.x,
                y=event.y,
                wheel=event.wheel,
                clicks=event.clicks,
            )

        if kind is EventKind.CURSOR:
            if event.x is None or event.y is None:
                raise RuntimeError("CURSOR requires x, y")

            return self._handle_cursor_query(event.x, event.y)

        if kind is EventKind.KEY:
            if event.key is None or event.flags is None or event.vKey is None:
                raise RuntimeError("KEY requires key, flags, vKey")

            return self._handle_key(
                key=event.key,
                flags=event.flags,
                vKey=event.vKey,
            )

        raise ValueError(f"Unhandled EventKind: {kind}")

    # ------------------------------------------------------------------
    # ROUTERS
    # ------------------------------------------------------------------
    def _handle_mouse_button(
        self,
        x: int,
        y: int,
        mouseStatus: XPLMMouseStatus,
        right: bool,
    ) -> int:
        info = self._pick_window_ex_at(x, y)
        if info is None:
            return 0

        consumed = self._dispatch_window_click(
            windowID=info.wid,
            x=x,
            y=y,
            mouseStatus=mouseStatus,
            right=right,
        )

        # XP-like: focus follows mouse-down when the window consumes the click
        if consumed and mouseStatus == self.xp.MouseDown:
            self._keyboard_focus_window = info.wid

        return consumed

    def _handle_mouse_wheel(self, x: int, y: int, wheel: int, clicks: int) -> int:
        info = self._pick_window_ex_at(x, y)
        if info is None:
            return 0

        return self._dispatch_window_wheel(
            windowID=info.wid,
            x=x,
            y=y,
            wheel=wheel,
            clicks=clicks,
        )

    def _handle_cursor_query(self, x: int, y: int) -> XPLMCursorStatus:
        info = self._pick_window_ex_at(x, y)
        if info is None:
            return self.xp.CursorDefault

        return self._dispatch_window_cursor(info.wid, x, y)

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
