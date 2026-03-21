# simless/libs/fake_xp/fake_widgets_api.py
# ===========================================================================
# FakeXPWidgetsAPI — XPWidgets public API mixin
#
# ROLE
#   Provide the exact XPPython3 xp widget API surface with strict XP semantics.
#
# DESIGN RULES
#   - No DearPyGui imports
#   - No rendering or geometry application
#   - No inferred behavior
#   - No validation beyond XP rules
#   - All state mutations go through _update_widget or mark _widgets_dirty
#
# This mixin is intended to be combined with a concrete backend that owns:
#   - self._widgets : Dict[XPWidgetID, WidgetInfo]
#   - self._z_order : List[XPWidgetID]
#   - self._widgets_dirty : bool
#   - self._require_widget(wid)
#   - self._update_widget(info, ...)
#   - self._kill_widget(wid)
#
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from simless.libs.fake_xp_interface import FakeXPInterface
from simless.libs.fake_xp_types import WidgetInfo, WindowExInfo
from XPPython3.xp_typing import XPWidgetClass, XPWidgetID, XPWidgetMessage, XPWidgetPropertyID

XPWidgetCallback = Callable[[int, int, Any, Any], int]


class FakeXPWidgetsAPI:
    xp: FakeXPInterface

    # ID generation
    _next_id: int
    _z_order: List[XPWidgetID]
    _focused_widget: Optional[XPWidgetID]

    # Interaction state
    _hover_widget: Optional[XPWidgetID]
    _drag_widget: Optional[XPWidgetID]

    # Message queue
    _message_queue: List[XPWidgetMessage]

    # Initialization guard
    _widgets_dirty: bool
    _widgets_initialized: bool

    # Backend helpers (implemented in FakeXPWidget)
    def _get_widget(self, wid: XPWidgetID) -> WidgetInfo:
        ...

    def _get_widget_windowex(self, wid: XPWidgetID) -> WindowExInfo:
        ...

    def _update_widget(
        self,
        info: WidgetInfo,
        *,
        visible: bool | None = None,
        descriptor: str | None = None,
        prop: tuple[int, Any] | None = None,
    ) -> None:
        ...

    def _kill_widget(self, wid: XPWidgetID) -> None:
        ...

    # ------------------------------------------------------------------
    # CREATE / DESTROY
    # ------------------------------------------------------------------
    def createWidget(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        visible: int,
        descriptor: str,
        is_root: int,
        parent: int,
        widget_class: XPWidgetClass,
    ) -> XPWidgetID:

        # 1. Allocate ID
        wid = XPWidgetID(self._next_id)
        self._next_id += 1

        # 2. Validate parent rules
        if is_root:
            if parent != 0:
                raise ValueError(f"Root widget {wid} must have parent=0")
            parent_wid = None
        else:
            if parent == 0:
                raise ValueError(f"Non-root widget {wid} cannot have parent=0")
            parent_wid = XPWidgetID(parent)
            self._get_widget(parent_wid)  # fail fast

        # 3. Create logical XPWidget
        info = WidgetInfo(
            wid=wid,
            widget_class=widget_class,
            parent=parent_wid,
            descriptor=descriptor,
            geometry=(left, top, right, bottom),
            visible=bool(visible),
        )

        if widget_class == self.xp.WidgetClass_TextField:
            info.edit_buffer = descriptor

        # 4. Root widget → create WindowEx
        if is_root:
            self._create_window_for_root_widget(wid, info)
            return wid

        # 5. Normal widget → attach to parent window
        self._attach_widget_to_parent_window(wid, info)

        self._widgets_initialized = False
        self._widgets_dirty = True

        return wid

    def destroyWidget(self, wid: XPWidgetID, destroy_children: int = 1) -> None:
        """
        Public XPWidgets API: destroy a widget, optionally destroying its subtree.

        This method performs *no backend operations* and does not directly mutate
        DPG state. It delegates to the internal `_kill_widget()` method, which
        performs structural deletion and queues backend deletions.
        """

        # XPWidgets API requires subtree deletion when destroy_children != 0.
        # Our internal `_kill_widget()` already destroys the entire subtree,
        # so we simply call it once.
        self._kill_widget(wid)

    # ------------------------------------------------------------------
    # GEOMETRY
    # ------------------------------------------------------------------
    def setWidgetGeometry(
        self,
        wid: XPWidgetID,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None:

        info = self._require_widget(wid)
        info.geometry = (left, top, right, bottom)

        # Invalidate backend geometry
        info.geom_applied = False
        info.container_geom_applied = None

        self._widgets_dirty = True

    def getWidgetGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        return self._require_widget(wid).geometry

    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        return self.getWidgetGeometry(wid)

    # ------------------------------------------------------------------
    # VISIBILITY
    # ------------------------------------------------------------------
    def showWidget(self, wid: XPWidgetID) -> None:
        info = self._require_widget(wid)
        self._update_widget(info, visible=True)

    def hideWidget(self, wid: XPWidgetID) -> None:
        info = self._require_widget(wid)
        self._update_widget(info, visible=False)

    def isWidgetVisible(self, wid: XPWidgetID) -> bool:
        return bool(self._require_widget(wid).visible)

    # ------------------------------------------------------------------
    # PROPERTIES
    # ------------------------------------------------------------------
    def setWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID, value: Any) -> None:
        info = self._require_widget(wid)
        self._update_widget(info, prop=(prop, value))

    def getWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID) -> Any:
        return self._require_widget(wid).properties.get(prop)

    # ------------------------------------------------------------------
    # CALLBACKS + MESSAGE DISPATCH
    # ------------------------------------------------------------------
    def addWidgetCallback(self, wid: XPWidgetID, callback: XPWidgetCallback) -> None:
        info = self._require_widget(wid)
        if callback not in info.callbacks:
            info.callbacks.append(callback)

    def sendMessageToWidget(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage,
        param1: Any,
        param2: Any,
    ) -> None:

        origin = wid
        current = wid
        visited: set[XPWidgetID] = set()

        while current and current not in visited:
            visited.add(current)
            info = self._require_widget(current)

            for cb in info.callbacks:
                cb(msg, origin, param1, param2)

            current = info.parent

        self._widgets_dirty = True

    # ------------------------------------------------------------------
    # HIERARCHY / HIT TESTING
    # ------------------------------------------------------------------
    def getParentWidget(self, wid: XPWidgetID) -> XPWidgetID:
        return self._require_widget(wid).parent

    def getWidgetForLocation(self, x: int, y: int) -> Optional[XPWidgetID]:
        for wid in reversed(self._z_order):
            info = self._require_widget(wid)
            if not info or not self._is_widget_effectively_visible(wid):
                continue

            left, top, right, bottom = info.geometry
            if left <= x < right and bottom <= y < top:
                return wid

        return None

    # ------------------------------------------------------------------
    # Z‑ORDER
    # ------------------------------------------------------------------
    def isWidgetInFront(self, wid: XPWidgetID) -> bool:
        return bool(self._z_order) and self._z_order[-1] == wid

    def bringWidgetToFront(self, wid: XPWidgetID) -> None:
        self._require_widget(wid)
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.append(wid)
            self._widgets_dirty = True

    def pushWidgetBehind(self, wid: XPWidgetID) -> None:
        self._require_widget(wid)
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)
            self._widgets_dirty = True

    # ------------------------------------------------------------------
    # KEYBOARD FOCUS
    # ------------------------------------------------------------------
    def getKeyboardFocus(self) -> XPWidgetID | None:
        return self._focused_widget

    def setKeyboardFocus(self, wid: XPWidgetID) -> None:
        self._require_widget(wid)
        self._focused_widget = wid
        self._widgets_dirty = True

    def loseKeyboardFocus(self, wid: XPWidgetID) -> None:
        self._require_widget(wid)
        if self._focused_widget == wid:
            self._focused_widget = None
            self._widgets_dirty = True

    # ------------------------------------------------------------------
    # DESCRIPTOR / CLASS
    # ------------------------------------------------------------------
    def getWidgetDescriptor(self, wid: XPWidgetID) -> str:
        return self._require_widget(wid).descriptor

    def setWidgetDescriptor(self, wid: XPWidgetID, text: str) -> None:
        info = self._require_widget(wid)
        self._update_widget(info, descriptor=text)

    def getWidgetClass(self, wid: XPWidgetID) -> XPWidgetClass:
        return self._require_widget(wid).widget_class

    def getWidgetUnderlyingWindow(self, wid: XPWidgetID) -> int:
        self._require_widget(wid)
        return 0

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------
    def _create_window_for_root_widget(self, wid: XPWidgetID, info: WidgetInfo):
        win_id = self.xp.createWindowEx(
            left=info.geometry[0],
            top=info.geometry[1],
            right=info.geometry[2],
            bottom=info.geometry[3],
            decoration=self.xp.WindowDecorationRoundRectangle,
            layer=self.xp.WindowLayerFloatingWindows,
        )

        win = self.xp.get_windowex(win_id)
        win.widget_root = wid
        win.widgets[wid] = info

    def _attach_widget_to_parent_window(self, wid: XPWidgetID, info: WidgetInfo):
        parent_wid = info.parent
        if parent_wid is None:
            raise RuntimeError(f"Internal error: non-root widget {wid} has no parent")

        win = self._get_widget_windowex(parent_wid)
        win.widgets[wid] = info

        parent_info = self._get_widget(parent_wid)
        parent_info.children.append(wid)

    def _require_widget(self, wid: XPWidgetID) -> WidgetInfo:
        """
        Return the WidgetInfo for the given XPWidgetID.

        Widgets are now stored inside their owning WindowExInfo instance, not in a
        global registry. This method searches all WindowEx objects and returns the
        authoritative WidgetInfo. If the widget does not exist, a fail-fast error
        is raised.
        """

        for win in self.xp.all_windowex():
            info = win.widgets.get(wid)
            if info is not None:
                return info

        raise RuntimeError(f"XPWidget {wid} does not exist")

    def _is_widget_effectively_visible(self, wid: XPWidgetID) -> bool:
        current = wid
        while current:
            info = self._require_widget(current)
            if not info.visible:
                return False
            current = info.parent
        return True
