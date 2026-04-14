# widget_manager.py

from __future__ import annotations

from typing import Dict, Iterable, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import DPGGeom, DPGOp, WGeom, WidgetInfo, WindowExInfo
from simless.libs.widget_render import WidgetRender
from XPPython3.xp_typing import XPWidgetClass, XPWidgetID

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
        geometry: WGeom,
        parent: Optional[XPWidgetID] = None,
        descriptor: str = "",
        visible: bool = True,
    ) -> WidgetInfo:

        wid = self.allocate_widget_id()

        info = WidgetInfo(
            wid=wid,
            widget_class=widget_class,
            window=window,
            _geometry=geometry,  # ← FIXED: use property, not _geometry
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
        window.add_to_z_order(wid)

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
        window.remove_from_z_order(wid)

        # Clear focus if needed (dirties window internally)
        if window.focused_widget == wid:
            window.clear_widget_focus()

        # Remove from registry
        self._widgets.pop(wid, None)

    def kill_all_widgets_in_window(self, window: WindowExInfo) -> None:
        root = window.widget_root
        if root is None:
            return

        self.destroy_widget(root)

        # Root already cleared by destroy_widget if needed
        window.clear_widget_focus()  # dirties window internally
        window._z_order.clear()  # direct clear is fine
        window._dirty_xp_to_dpg = True  # ensure sync after mass deletion

    def raise_widget(self, wid: XPWidgetID) -> None:
        info = self.require_info(wid)
        info.window.raise_widget(wid)  # dirties window internally

    def lower_widget(self, wid: XPWidgetID) -> None:
        info = self.require_info(wid)
        info.window.lower_widget(wid)  # dirties window internally

    def set_focus(self, wid: Optional[XPWidgetID]) -> None:
        if wid is None:
            return
        info = self.require_info(wid)
        info.window.set_focused_widget(wid)
        info.window._dirty_xp_to_dpg = True

    def clear_focus(self, window: WindowExInfo) -> None:
        window.clear_widget_focus()
        window._dirty_xp_to_dpg = True

    def get_focused_widget(self, window: WindowExInfo) -> Optional[XPWidgetID]:
        return window.focused_widget

    def hit_test(self, window: WindowExInfo, x: int, y: int) -> Optional[XPWidgetID]:
        """
        Return the topmost widget at (x, y) in window coordinates.
        """
        for wid in reversed(window.z_order):
            info = self.get_widget(wid)
            if info and info.geometry.contains(x, y):
                return wid
        return None

    def iter_subtree(self, root: XPWidgetID) -> Iterable[WidgetInfo]:
        stack = [root]
        while stack:
            wid = stack.pop()
            info = self.get_widget(wid)
            if info is None:
                continue
            yield info
            stack.extend(reversed(info.children))

    def iter_window_widgets(self, window: WindowExInfo) -> Iterable[WidgetInfo]:
        root = window.widget_root
        if root is None:
            return ()
        return self.iter_subtree(root)

    def dispatch_message(self, wid, msg, p1, p2):
        info = self.require_info(wid)

        # 1. Plugin handlers (child first)
        for cb in info.callbacks:
            try:
                handled = cb(msg, wid, p1, p2)
            except Exception:
                handled = 0

            if handled:
                return 1

        # 2. Bubble to parent plugin handlers
        if info.parent is not None:
            handled = self.dispatch_message(info.parent, msg, p1, p2)
            if handled:
                return 1

        # 3. Default handler LAST
        if self._default_widget_handler(msg, wid, p1, p2):
            return 1

        return 0

    def _default_widget_handler(self, msg, wid, p1, p2) -> int:
        info = self.require_info(wid)

        # Close box
        if msg == self.fake_xp.Message_CloseButtonPushed:
            # XP behavior: hide the root window
            self.fake_xp.hideWidget(wid)
            return 1

        # (You can add more default behaviors here later)

        return 0
