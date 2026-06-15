# widget_manager.py

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import DPGOp, LocalGeom, WidgetInfo, WindowExInfo, XPGeom, XPPoint
from simless.libs.widget_render import WidgetRender
from xp_typing import XPWidgetClass, XPWidgetID, XPWidgetMessage

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
            local_geom=LocalGeom.from_xpgeom(abs_geom, window.frame),
            parent=parent,
            _descriptor=descriptor,
            _visible=visible,
        )

        self._widgets[wid] = info

        # Attach to parent
        if parent is not None:
            pinfo = self.require_info(parent)
            pinfo.add_child(wid)  # dirties window internally

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
        info = self.require_info(wid)
        fw = info.window.focused_widget

        if fw == wid:
            return  # no-op

        if fw is not None:
            self.clear_focus(fw)

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

    def hit_test(
            self,
            root_wid: XPWidgetID,
            xp_pt: XPPoint,
            recursive: bool = True,
    ) -> Optional[XPWidgetID]:
        """
        XPWidgets API: return the topmost widget at (x, y) under the given root.
        Coordinates are in the window's GLOBAL coordinate system.
        """

        info = self.require_info(root_wid)

        # 1. Hit test this widget using GLOBAL geometry
        if not info.visible or not info.xp_geom.contains(xp_pt):
            return None

        # 2. If recursive, search children in front-to-back order
        if recursive:
            for child in reversed(info.children):
                hit = self.hit_test(child, xp_pt, recursive)
                if hit is not None:
                    return hit

        # 3. No child hit → this widget is the hit
        return info.wid

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

    def handle_input_msg(
            self,
            info: WidgetInfo,
            msg: XPWidgetMessage | int,
            p1: Any = None,
            p2: Any = None,
            process_input_handler: Optional[Callable[..., None]] = None
    ) -> bool:
        """
        Suitable handler for default and any input widget.  Allows for callback handling on ENTER
        """
        xp = self.fake_xp

        # Only text fields handle text input
        if info.widget_class != xp.WidgetClass_TextField:
            return False
        if msg != xp.Msg_KeyPress:
            return False

        key, flags, vkey = p1

        text = info.descriptor

        # ---------------------------------------------------------
        # ENTER → commit callback
        # ---------------------------------------------------------
        if key == 13 and process_input_handler is not None:
            process_input_handler()
            return True

        # ---------------------------------------------------------
        # ESC → lose focus
        # ---------------------------------------------------------
        if key == 27:
            xp.loseKeyboardFocus(info.wid)
            return True

        # ---------------------------------------------------------
        # BACKSPACE
        # ---------------------------------------------------------
        if key == 8:
            if text:
                info.set_descriptor(text[:-1])
            return True

        # ---------------------------------------------------------
        # Printable ASCII characters
        # ---------------------------------------------------------
        if 32 <= key <= 126:
            info.set_descriptor(text + chr(key))
            return True

        # ---------------------------------------------------------
        # All other keys → let XPWidgets or plugins handle
        # ---------------------------------------------------------
        return False

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
            if winfo.xp_geom.contains(p1):
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
        # 3. Default-if-unhandled class behavior
        # ---------------------------------------------------------
        if self._class_behavior_default(info, msg, p1, p2):
            return 1

        return 0

    # ------------------------------------------------------------------
    # DEFAULT-IF-UNHANDLED CLASS BEHAVIOR (FALLBACKS ONLY)
    # ------------------------------------------------------------------
    def _class_behavior_default(self, info, msg, p1, p2):
        xp = self.fake_xp

        # ---------------------------------------------------------
        # TEXT FIELD DEFAULT KEY HANDLING (XP-authentic)
        # ---------------------------------------------------------
        if self.handle_input_msg(info, msg, p1, p2):
            return 1

        # ---------------------------------------------------------
        # CLOSE BOX FALLBACK
        # ---------------------------------------------------------
        if msg == xp.Message_CloseButtonPushed:
            self.require_info(info.window.widget_root).set_visible(False)
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
        dpg_id = info.dpg_id
        assert dpg_id is not None
        dpg_text = self.fake_xp.graphics_manager.dpg_get_value(dpg_id)
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

        self._dispatch_message(
            info.wid,
            self.fake_xp.Msg_TextFieldChanged,
            0,
            0
        )
