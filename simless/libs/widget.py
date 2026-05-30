# widget_manager.py

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import DPGOp, WidgetInfo, WindowExInfo, XPGeom
from simless.libs.widget_render import WidgetRender
from XPPython3.xp_typing import XPWidgetClass, XPWidgetID, XPWidgetMessage

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class WidgetManager(WidgetRender):
    """
    Global XPWidget registry + XP→DPG sync engine.

    Responsibilities:
      - Allocate XPWidgetIDs
      - Own the global WidgetInfo registry
      - Maintain parent/child relationships
      - Structural realization (ensure_dpg)
      - XP→DPG sync (geometry + visibility)
      - Draw callback dispatch
      - Widget destruction
      - Window‑scoped iteration
      - Z‑order mutation (per-window)
      - Focus mutation (per-window)
      - Hit-testing
    """

    def __init__(self, fake_xp: FakeXP) -> None:
        self.fake_xp = fake_xp

        self._widgets: Dict[XPWidgetID, WidgetInfo] = {}
        self._next_widget_id: int = 1
        self._msg_queue = []
        self.gm = fake_xp.graphics_manager
        self.wm = fake_xp.window_manager

    def allocate_widget_id(self) -> XPWidgetID:
        wid = XPWidgetID(self._next_widget_id)
        self._next_widget_id += 1
        return wid

    def get_widget(self, wid: XPWidgetID) -> Optional[WidgetInfo]:
        return self._widgets.get(wid)

    def require_info(self, wid: XPWidgetID) -> WidgetInfo:
        info = self._widgets.get(wid)
        if info is None:
            raise KeyError(f"Widget {wid} does not exist")
        return info

    def create_widget(
        self,
        *,
        widget_class: XPWidgetClass,
        window: WindowExInfo,
        abs_geom: XPGeom,
        parent: Optional[XPWidgetID] = None,
        descriptor: str = "",
        visible: bool = True,
    ) -> WidgetInfo:

        wid = self.allocate_widget_id()

        info = WidgetInfo(
            wid=wid,
            widget_class=widget_class,
            window=window,
            abs_geom_param=abs_geom,
            parent=parent,
            _descriptor=descriptor,
            _visible=visible,
        )

        self._widgets[wid] = info

        # Attach to parent
        if parent is not None:
            pinfo = self.require_info(parent)
            pinfo.add_child(wid)  # dirties window internally

        # If window has no root, this becomes root
        if window.widget_root is None:
            window.set_widget_root(wid)

        # Add to z-order (dirties window internally)
        window.add_to_widget_z_order(wid)

        return info

    # ------------------------------------------------------------
    # DESTRUCTION
    # ------------------------------------------------------------

    def destroy_widget(self, wid: XPWidgetID) -> None:
        """
        Destroy a widget and its subtree.
        Structural only: DPG deletions are queued.
        """
        info = self.get_widget(wid)
        if info is None:
            return

        window = info.window

        # Recursively destroy children
        for child_id in list(info.children):
            self.destroy_widget(child_id)

        # Queue DPG deletions
        if info.dpg_id is not None:
            self.gm.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.dpg_id,))
        if info.container_id is not None and info.container_id != info.dpg_id:
            self.gm.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.container_id,))

        # Detach from parent
        if info.parent is not None:
            pinfo = self.require_info(info.parent)
            pinfo.remove_child(wid)  # dirties window internally

        # Clear window root if needed
        if window.widget_root == wid:
            window.set_widget_root(None)

        # Remove from z-order (dirties window internally)
        window.remove_from_widget_z_order(wid)

        # Clear focus if needed (dirties window internally)
        if window.focused_widget == wid:
            window.set_focused_widget(None)

        # Remove from registry
        self._widgets.pop(wid, None)

    def raise_widget(self, wid: XPWidgetID) -> None:
        info = self.require_info(wid)
        info.window.raise_widget(wid)  # dirties window internally

    def lower_widget(self, wid: XPWidgetID) -> None:
        info = self.require_info(wid)
        info.window.lower_widget(wid)  # dirties window internally

    def set_focus(self, wid: XPWidgetID) -> None:
        self.queue_msg(
            wid,
            self.fake_xp.Msg_KeyTakeFocus,
            None,
            None,
        )

    def clear_focus(self, wid: XPWidgetID) -> None:
        self.queue_msg(
            wid,
            self.fake_xp.Msg_KeyLoseFocus,
            None,
            None,
        )

    def iter_window_widgets(self, window: WindowExInfo) -> Iterable[WidgetInfo]:
        root = window.widget_root
        if root is None:
            return ()
        return self._iter_subtree(root)

    def _iter_subtree(self, root: XPWidgetID) -> Iterable[WidgetInfo]:
        stack = [root]
        while stack:
            wid = stack.pop()
            info = self.get_widget(wid)
            if info is None:
                continue
            yield info
            # Push children in reverse so leftmost child is popped first
            for child in reversed(info.children):
                stack.append(child)

    def queue_msg(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage | int,
        p1: Any = None,
        p2: Any = None,
    ) -> None:
        self._msg_queue.append((wid, msg, p1, p2))

    def drain_msg_queue(self) -> None:
        while self._msg_queue:
            wid, msg, p1, p2 = self._msg_queue.pop(0)
            if msg in (self.fake_xp.Msg_MouseDown, self.fake_xp.Msg_MouseUp):
                # Mouse events → full routing
                self._route_widget_message(wid, msg, p1, p2)
            else:
                # API messages → direct dispatch
                self._dispatch_message(wid, msg, p1, p2)

    # ------------------------------------------------------------------
    # DISPATCH PIPELINE (XP-authentic)
    # ------------------------------------------------------------------
    def _route_widget_message(self, root_id, msg, p1, p2):
        """
        XP-authentic routing:
          1) root first
          2) children in reverse z-order (hit-test)
          3) root last chance
        """
        xp = self.fake_xp
        root_info = self.require_info(root_id)

        # 1) Root receives event first
        if self._dispatch_message(root_id, msg, p1, p2):
            return 1

        # 2) Children in reverse z-order
        for wid in reversed(root_info.window.widget_z_order):
            if wid == root_id:
                continue

            winfo = xp.widget_manager.get_widget(wid)
            if not winfo:
                continue

            # Hit-test child
            if winfo.abs_xpgeom.contains(p1):
                if self._dispatch_message(wid, msg, p1, p2):
                    return 1

        # 3) Root gets a second chance
        return self._dispatch_message(root_id, msg, p1, p2)

    def _dispatch_message(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage | int,
        p1: Any,
        p2: Any,
    ) -> int:

        info: WidgetInfo = self.require_info(wid)
        xp = self.fake_xp

        # ---------------------------------------------------------
        # 0. Focus messages: deliver to widget FIRST
        # ---------------------------------------------------------
        if msg in (xp.Msg_KeyTakeFocus, xp.Msg_KeyLoseFocus):

            # 0a. Deliver to widget/plugin handlers
            for cb in info.callbacks:
                if cb(msg, wid, p1, p2):
                    return 1

            # 0b. Widget did NOT consume → apply focus change
            if msg == xp.Msg_KeyTakeFocus:
                self._apply_focus_take(wid)
            else:
                self._apply_focus_lose(wid)

            return 1  # focus messages never bubble

        # ---------------------------------------------------------
        # 1. Plugin handlers
        # ---------------------------------------------------------
        for cb in info.callbacks:
            if cb(msg, wid, p1, p2):
                return 1

        # ---------------------------------------------------------
        # 2. Bubble to parent
        # ---------------------------------------------------------
        if info.parent is not None:
            if self._dispatch_message(info.parent, msg, p1, p2):
                return 1

        # ---------------------------------------------------------
        # 3. Additional class behavior (non-blocking)
        # ---------------------------------------------------------
        self._class_behavior_additional(info, msg, p1, p2)

        # ---------------------------------------------------------
        # 4. Default-if-unhandled class behavior
        # ---------------------------------------------------------
        if self._class_behavior_default(info, msg, p1, p2):
            return 1

        return 0

    # ------------------------------------------------------------------
    # ADDITIONAL CLASS BEHAVIOR (NON-BLOCKING)
    # ------------------------------------------------------------------
    def _class_behavior_additional(
        self,
        info: WidgetInfo,
        msg: XPWidgetMessage | int,
        p1: Any,
        p2: Any,
    ) -> None:
        xp = self.fake_xp

        # ---------------------------------------------------------
        # BUTTON: Generate PushButtonPressed on parent
        # ---------------------------------------------------------
        if info.widget_class == xp.WidgetClass_Button:
            if msg == xp.Msg_MouseUp:
                if info.parent is not None:
                    parent_info = self.require_info(info.parent)

                    # Deliver PushButtonPressed to parent
                    for cb in parent_info.callbacks:
                        cb(
                            xp.Msg_PushButtonPressed,
                            info.parent,  # inWidget = parent
                            info.wid,  # param1 = button ID
                            0  # param2 unused
                        )
                # Additional behavior NEVER returns handled

    # ------------------------------------------------------------------
    # DEFAULT-IF-UNHANDLED CLASS BEHAVIOR (FALLBACKS ONLY)
    # ------------------------------------------------------------------
    def _class_behavior_default(self, info, msg, p1, p2):
        xp = self.fake_xp

        # ---------------------------------------------------------
        # BUTTON DEFAULT BEHAVIOR (no arming, no contains)
        # ---------------------------------------------------------
        if info.widget_class == xp.WidgetClass_Button:

            # MouseDown → consume
            if msg == xp.Msg_MouseDown:
                return 1

            # MouseUp → generate PushButtonPressed (or close)
            if msg == xp.Msg_MouseUp:
                parent = info.parent

                # If this button *is* the window's close button:
                if info.window and info.window.widget_close == info.wid:
                    event = xp.Message_CloseButtonPushed
                else:
                    event = xp.Msg_PushButtonPressed

                if parent:
                    self._dispatch_message(
                        parent,
                        event,
                        info.wid,  # p1 = button ID
                        0
                    )
                return 1

        # ---------------------------------------------------------
        # TEXT FIELD DEFAULT KEY HANDLING (XP-authentic)
        # ---------------------------------------------------------
        if info.widget_class == xp.WidgetClass_TextField:
            if msg == xp.Msg_KeyPress:
                key, flags, vkey = p1

                text = info.descriptor or ""
                cursor = info.properties.get(xp.Property_EditFieldSelStart, 0)
                sel_end = info.properties.get(xp.Property_EditFieldSelEnd, cursor)

                # Collapse selection
                if sel_end != cursor:
                    start = min(cursor, sel_end)
                    end = max(cursor, sel_end)
                    text = text[:start] + text[end:]
                    cursor = start
                    sel_end = start

                # Backspace / Delete
                if key in (8, 127):
                    if cursor > 0:
                        text = text[:cursor - 1] + text[cursor:]
                        cursor -= 1

                # Printable ASCII
                elif 32 <= key <= 126:
                    ch = chr(key)
                    text = text[:cursor] + ch + text[cursor:]
                    cursor += 1

                # Clamp cursor
                if cursor < 0:
                    cursor = 0
                if cursor > len(text):
                    cursor = len(text)

                # Write back
                info.set_descriptor(text)
                info.properties[xp.Property_EditFieldSelStart] = cursor
                info.properties[xp.Property_EditFieldSelEnd] = cursor

                return 1


        # ---------------------------------------------------------
        # CLOSE BOX FALLBACK
        # ---------------------------------------------------------
        if msg == xp.Message_CloseButtonPushed:
            info.set_visible(False)
            return 1

        return 0

    def _apply_focus_take(self, wid: XPWidgetID) -> None:
        """
        Apply focus to this widget.
        Called ONLY after xpMsg_KeyTakeFocus has been dispatched
        and NOT consumed by the widget/plugin.
        """
        info = self.require_info(wid)
        window = info.window
        prev = window.focused_widget

        if prev == wid:
            return

        if prev:
            self._apply_focus_lose(prev)

        window.set_focused_widget(wid)

    def _apply_focus_lose(self, wid: XPWidgetID) -> None:
        """
        Remove focus from this widget.
        Called ONLY after xpMsg_KeyLoseFocus has been dispatched
        and NOT consumed by the widget/plugin.
        """
        info = self.require_info(wid)
        window = info.window

        if info.widget_class == self.fake_xp.WidgetClass_TextField and bool(info.callbacks):
            self._replay_dpg_input_into_xp(info)

        # Only clear if this widget actually has focus
        if window.focused_widget == wid:
            window.set_focused_widget(None)

    def _replay_dpg_input_into_xp(self, info: WidgetInfo) -> None:
        # ---------------------------------------------------------
        # 1) Get current text from DPG
        # ---------------------------------------------------------
        dpg_text = self.fake_xp.graphics_manager.dpg_get_value(info.dpg_id)
        if not isinstance(dpg_text, str):
            return

        # ---------------------------------------------------------
        # 2) Clear XP widget (descriptor + cursor)
        # ---------------------------------------------------------
        self.fake_xp.setWidgetDescriptor(info.wid, "")
        self.fake_xp.setWidgetProperty(info.wid, self.fake_xp.Property_EditFieldSelStart, 0)
        self.fake_xp.setWidgetProperty(info.wid, self.fake_xp.Property_EditFieldSelEnd, 0)

        cursor = 0

        # ---------------------------------------------------------
        # 3) Replay each character as xpMsg_KeyPress
        # ---------------------------------------------------------
        for ch in dpg_text:
            key = ord(ch)

            # Send xpMsg_KeyPress to widget
            self._dispatch_message(
                info.wid,
                self.fake_xp.Msg_KeyPress,
                (key, self.fake_xp.input_manager.make_xp_flags(key), key),
                0
            )

            # Advance cursor locally
            cursor += 1

            # Update cursor properties
            self.fake_xp.setWidgetProperty(info.wid, self.fake_xp.Property_EditFieldSelStart, cursor)
            self.fake_xp.setWidgetProperty(info.wid, self.fake_xp.Property_EditFieldSelEnd, cursor)

        # ---------------------------------------------------------
        # 4) After replay, set DPG input text = XP descriptor
        # ---------------------------------------------------------
        final_text = self.fake_xp.getWidgetDescriptor(info.wid)
        self.fake_xp.graphics_manager.dpg_set_value(info.dpg_id, final_text)
