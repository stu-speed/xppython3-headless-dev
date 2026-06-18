# ===========================================================================
# FakeXPInput — input routing subsystem mixin for FakeXP
#
# ROLE
#   Provide a minimal, deterministic, XPLM-style input façade for simless
#   execution. This subsystem owns the input event queue and routes events
#   to WindowEx callbacks using XP-semantic hit-testing, capture, and
#   keyboard-focus rules. After window-level routing, events may be routed
#   into the XPWidget tree (if present) using XP-authentic bubbling.
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

from typing import Any, List, Optional, TYPE_CHECKING

import dearpygui.dearpygui as dpg

from simless.libs.fake_xp_types import EventInfo, EventKind, XPPoint, XPWidgetID
from xp_typing import XPLMCursorStatus, XPLMMouseStatus, XPLMWindowID

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class InputManager:
    """Input routing subsystem mixin for FakeXP."""

    # ------------------------------------------------------------------
    # Input state
    # ------------------------------------------------------------------
    _keyboard_focus_window: Optional[XPLMWindowID]
    _input_events: List[EventInfo]
    _mouse_capture_window: Optional[XPLMWindowID]
    _mouse_button_down: bool

    def __init__(self, fake_xp: FakeXP) -> None:
        """Initialize internal input state. Called by FakeXP during construction."""
        self._keyboard_focus_window = None
        self._input_events = []
        self._mouse_capture_window = None
        self._mouse_button_down = False
        self.fake_xp = fake_xp

    # ------------------------------------------------------------------
    # INPUT QUEUE (engine-owned)
    # ------------------------------------------------------------------
    def queue_input_event(self, event: EventInfo) -> None:
        """Enqueue a normalized EventInfo object.

        Called by graphics/backend adapters only.
        """
        self._input_events.append(event)

    def drain_input_events(self) -> None:
        while self._input_events:
            event = self._input_events.pop(0)
            self.process_event_info(event)

    # ------------------------------------------------------------------
    # FOCUS CONTROL
    # ------------------------------------------------------------------
    def clear_keyboard_focus(self) -> None:
        """Explicitly clear keyboard focus."""
        self._keyboard_focus_window = None

    def install_dpg_input_callbacks(self) -> None:
        with dpg.handler_registry():  # type: ignore
            dpg.add_mouse_down_handler(
                callback=lambda sender, app_data: (
                    self.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.MOUSE_BUTTON,
                            dpg_x=int(dpg.get_mouse_pos(local=False)[0]),
                            dpg_y=int(dpg.get_mouse_pos(local=False)[1]),
                            dpg_vp_height=dpg.get_viewport_client_height(),
                            state="down",
                            button=int(app_data) if isinstance(app_data, int) else 0,
                        )
                    )
                )
            )

            dpg.add_mouse_release_handler(
                callback=lambda sender, app_data: (
                    self.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.MOUSE_BUTTON,
                            dpg_x=int(dpg.get_mouse_pos(local=False)[0]),
                            dpg_y=int(dpg.get_mouse_pos(local=False)[1]),
                            dpg_vp_height=dpg.get_viewport_client_height(),
                            state="up",
                            button=int(app_data) if isinstance(app_data, int) else 0,
                        )
                    )
                )
            )

            dpg.add_mouse_move_handler(
                callback=lambda sender, app_data: (
                    self.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.CURSOR,
                            dpg_x=int(dpg.get_mouse_pos(local=False)[0]),
                            dpg_y=int(dpg.get_mouse_pos(local=False)[1]),
                            dpg_vp_height=dpg.get_viewport_client_height(),
                        )
                    )
                )
            )

            dpg.add_mouse_wheel_handler(
                callback=lambda sender, app_data: (
                    self.queue_input_event(
                        EventInfo.from_dpg(
                            kind=EventKind.MOUSE_WHEEL,
                            dpg_x=int(dpg.get_mouse_pos(local=False)[0]),
                            dpg_y=int(dpg.get_mouse_pos(local=False)[1]),
                            dpg_vp_height=dpg.get_viewport_client_height(),
                            wheel=int(app_data),
                            clicks=int(app_data),
                        )
                    )
                )
            )

            dpg.add_key_press_handler(
                callback=lambda sender, app_data: (
                    self.queue_input_event(
                        EventInfo.from_xp(
                            kind=EventKind.KEY,
                            key=int(app_data),
                            flags=self.make_xp_flags(app_data),
                            vKey=int(app_data),
                        )
                    )
                )
            )

    def make_xp_flags(self, key: int) -> int:
        """
        Build XPWidgets key flags from a single DPG key code.
        No modifier state is tracked; modifier keys set their own bits.
        """
        XP_KEYFLAG_SHIFT = 1
        XP_KEYFLAG_CTRL = 2
        XP_KEYFLAG_ALT = 4
        XP_KEYFLAG_DOWN = 8

        flags = XP_KEYFLAG_DOWN

        if key == dpg.mvKey_Shift:
            flags |= XP_KEYFLAG_SHIFT
        elif key == dpg.mvKey_Control:
            flags |= XP_KEYFLAG_CTRL
        elif key == dpg.mvKey_Alt:
            flags |= XP_KEYFLAG_ALT

        return flags

    # ------------------------------------------------------------------
    # SINGLE RUNNER ENTRY POINT (typed)
    # ------------------------------------------------------------------
    def process_event_info(self, event: EventInfo) -> Any:
        if event.kind is EventKind.MOUSE_BUTTON:
            if event.state is None:
                raise RuntimeError("MOUSE_BUTTON requires state")

            mouse_status = (
                self.fake_xp.MouseDown if event.state == "down" else self.fake_xp.MouseUp
            )

            xp_pt = event.xp_pt
            assert xp_pt is not None
            return self._handle_mouse_button(
                xp_pt=event.xp_pt,
                mouseStatus=mouse_status,
                right=event.right,
            )

        if event.kind is EventKind.MOUSE_WHEEL:
            if event.wheel is None or event.clicks is None:
                raise RuntimeError("MOUSE_WHEEL requires wheel, clicks")
            xp_pt = event.xp_pt
            assert xp_pt is not None
            return self._handle_mouse_wheel(
                xp_pt=event.xp_pt,
                wheel=event.wheel,
                clicks=event.clicks,
            )

        if event.kind is EventKind.CURSOR:
            xp_pt = event.xp_pt
            assert xp_pt is not None
            return self._handle_cursor_query(event.xp_pt)

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
    # WINDOW DISPATCH HELPERS (engine-invoked only)
    # ------------------------------------------------------------------
    def _dispatch_window_click(
            self,
            windowID: XPLMWindowID,
            xp_pt: XPPoint,
            mouseStatus: XPLMMouseStatus,
            right: bool = False,
    ) -> int:
        info = self.fake_xp.window_manager.require_info(windowID)
        if not info.client.contains(xp_pt):
            return 0

        cb = info.right_click_cb if right else info.click_cb
        if cb is None:
            return 0

        return int(cb(windowID, xp_pt.x, xp_pt.y, mouseStatus, info.refcon))

    def _dispatch_window_key(
            self,
            windowID: XPLMWindowID,
            key: int,
            flags: int,
            vKey: int,
            losingFocus: int,
    ) -> int:
        info = self.fake_xp.window_manager.require_info(windowID)
        if info.key_cb is None:
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

    def _dispatch_window_wheel(self,
                               windowID: XPLMWindowID,
                               xp_pt: XPPoint,
                               wheel: int,
                               clicks: int,
                               ) -> int:
        info = self.fake_xp.window_manager.require_info(windowID)
        if info.wheel_cb is None:
            return 0

        return int(info.wheel_cb(windowID, xp_pt.x, xp_pt.y, wheel, clicks, info.refcon))

    def _dispatch_window_cursor(
            self,
            windowID: XPLMWindowID,
            xp_pt: XPPoint,
    ) -> XPLMCursorStatus:
        info = self.fake_xp.window_manager.require_info(windowID)
        if info.cursor_cb is None:
            return self.fake_xp.CursorDefault

        return info.cursor_cb(windowID, xp_pt.x, xp_pt.y, info.refcon)

    # ------------------------------------------------------------------
    # WIDGET DISPATCH HELPERS
    # ------------------------------------------------------------------
    def _dispatch_widget_wheel(
            self,
            widgetID: XPWidgetID,
            wheel: int,
            clicks: int
    ) -> int:
        """
        Deliver xpMsg_MouseWheel to a widget and bubble upward.
        Wheel events use (wheel, clicks) as parameters.
        Returns 1 if handled.
        """
        xp = self.fake_xp
        wid = widgetID

        params = (wheel, clicks)

        while wid is not None:
            handled = self.fake_xp.widget_manager._dispatch_message(
                wid,
                xp.Msg_MouseWheel,
                params,
                0
            )
            if handled:
                return 1

            info = self.fake_xp.widget_manager.require_info(wid)
            wid = info.parent

        return 0

    def _dispatch_widget_key(
            self,
            widgetID: XPWidgetID,
            key: int,
            flags: int,
            vKey: int
    ) -> int:
        """
        Deliver xpMsg_KeyPress to a widget and bubble upward.
        Key events use inParam1 = (key, flags, vkey).
        Returns 1 if handled.
        """
        xp = self.fake_xp
        wid = widgetID

        inParam1 = (key, flags, vKey)

        while wid is not None:
            handled = self.fake_xp.widget_manager._dispatch_message(
                wid,
                xp.Msg_KeyPress,
                inParam1,
                0
            )
            if handled:
                return 1

            info = self.fake_xp.widget_manager.require_info(wid)
            wid = info.parent

        return 0

    # ------------------------------------------------------------------
    # ROUTERS
    # ------------------------------------------------------------------
    def _handle_cursor_query(self, xp_pt: XPPoint) -> XPLMCursorStatus:
        if self._mouse_capture_window is not None:
            info = self.fake_xp.window_manager.get_info(self._mouse_capture_window)
        else:
            info = self.fake_xp.window_manager.hit_test(xp_pt)

        if info is None:
            return self.fake_xp.CursorDefault

        win_id = info.wid
        assert win_id is not None
        return self._dispatch_window_cursor(info.wid, xp_pt)

    def _handle_mouse_button(
            self,
            xp_pt: XPPoint,
            mouseStatus: XPLMMouseStatus,
            right: bool,
    ) -> int:

        xp = self.fake_xp

        # ------------------------------------------------------------
        # 1) Debounce MouseDown
        # ------------------------------------------------------------
        if mouseStatus == xp.MouseDown:
            if self._mouse_button_down:
                return 0
            self._mouse_button_down = True

        elif mouseStatus == xp.MouseUp:
            self._mouse_button_down = False

        # ------------------------------------------------------------
        # 2) Determine target window
        #    Capture bypasses hit-testing entirely
        # ------------------------------------------------------------
        if self._mouse_capture_window is not None:
            info = xp.window_manager.get_info(self._mouse_capture_window)
        else:
            info = xp.window_manager.hit_test(xp_pt)

        if info is None:
            return 0

        win_id = info.wid
        assert win_id is not None

        # ------------------------------------------------------------
        # 3) Drag-to-front (XP-authentic)
        #    Happens BEFORE dispatch, regardless of consumption.
        # ------------------------------------------------------------
        if mouseStatus == xp.MouseDown:
            if info.frame.contains(xp_pt):
                xp.window_manager.bring_to_front(info)

        # ------------------------------------------------------------
        # 4) Queue widget message to ROOT widget
        #    (Dispatcher handles all widget routing)
        # ------------------------------------------------------------
        root_id = info.widget_root
        if root_id:
            if mouseStatus == xp.MouseDown:
                target_widget = xp.widget_manager.hit_test(root_id, xp_pt)
                if target_widget:
                    xp.widget_manager.set_focus(target_widget)

            xp.widget_manager.queue_msg(
                wid=root_id,
                msg=(xp.Msg_MouseDown if mouseStatus == xp.MouseDown else xp.Msg_MouseUp),
                p1=xp_pt,
                p2=right,
            )

        # ------------------------------------------------------------
        # 5) Dispatch window click callback
        #    (Window callbacks run BEFORE widget system)
        # ------------------------------------------------------------
        consumed = self._dispatch_window_click(
            windowID=info.wid,
            xp_pt=xp_pt,
            mouseStatus=mouseStatus,
            right=right,
        )

        # ------------------------------------------------------------
        # 6) Capture on MouseDown
        # ------------------------------------------------------------
        if consumed and mouseStatus == xp.MouseDown:
            self._mouse_capture_window = info.wid
            self._keyboard_focus_window = info.wid

        # ------------------------------------------------------------
        # 7) Release capture AFTER dispatch
        # ------------------------------------------------------------
        if mouseStatus == xp.MouseUp:
            if self._mouse_capture_window == info.wid:
                self._mouse_capture_window = None

        return consumed

    def _handle_mouse_wheel(
            self,
            xp_pt: XPPoint,
            wheel: int,
            clicks: int,
    ) -> int:
        info = self.fake_xp.window_manager.hit_test(xp_pt)
        if info is None:
            return 0

        # 1) Window wheel callback
        consumed = self._dispatch_window_wheel(
            windowID=info.wid,
            xp_pt=xp_pt,
            wheel=wheel,
            clicks=clicks,
        )
        if consumed:
            return 1

        # 2) Widget wheel callback (if any)
        root_id = info.widget_root
        if root_id:
            target_widget = self.fake_xp.widget_manager.hit_test(root_id, xp_pt)
            if target_widget:
                return self._dispatch_widget_wheel(
                    widgetID=target_widget,
                    wheel=wheel,
                    clicks=clicks,
                )

        return 0

    def _handle_key(self, key: int, flags: int, vKey: int) -> int:
        if self._keyboard_focus_window is None:
            return 0

        # 1) Window key callback
        consumed = self._dispatch_window_key(
            windowID=self._keyboard_focus_window,
            key=key,
            flags=flags,
            vKey=vKey,
            losingFocus=0,
        )
        if consumed:
            return 1

        # 2) Widget key callback (if widget focus is tracked)
        info = self.fake_xp.window_manager.require_info(self._keyboard_focus_window)
        widget_focus = info.focused_widget
        if widget_focus is None:
            return 0
        widget_info = self.fake_xp.widget_manager.require_info(widget_focus)
        if widget_info.widget_class == self.fake_xp.WidgetClass_TextField and bool(widget_info.callbacks):
            # Let DPG handle input.  Process on focus loss.
            return 0

        return self._dispatch_widget_key(
            widgetID=widget_focus,
            key=key,
            flags=flags,
            vKey=vKey,
        )
