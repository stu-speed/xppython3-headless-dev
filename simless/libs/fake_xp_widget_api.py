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

from typing import Any, cast, List, Optional, Tuple, TYPE_CHECKING

from simless.libs.fake_xp_types import WidgetInfo, WindowExInfo, XPWidgetCallback
from XPPython3.xp_typing import XPWidgetClass, XPWidgetID, XPWidgetMessage, XPWidgetPropertyID

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPWidgetsAPI:
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

    @property
    def fake_xp(self) -> FakeXP:
        return cast("FakeXP", cast(object, self))

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

        wid = XPWidgetID(self._next_id)
        self._next_id += 1

        # ---------------------------------------------------------
        # ROOT WIDGET PATH (early return, no else needed)
        # ---------------------------------------------------------
        if is_root:
            if parent != 0:
                raise ValueError(f"Root widget {wid} must have parent=0")

            # Create WindowEx FIRST
            window_info = self._create_window_for_root_geometry(left, top, right, bottom)

            # Create widget
            info = WidgetInfo(
                wid=wid,
                widget_class=widget_class,
                window=window_info,
                parent=None,
                _geometry=(left, top, right, bottom),
                _descriptor=descriptor,
                _visible=bool(visible),
            )

            if widget_class == self.fake_xp.WidgetClass_TextField:
                info.edit_buffer = descriptor

            # Register + mark as root
            window_info.widgets[wid] = info
            window_info._widget_root = wid

            return wid

        # ---------------------------------------------------------
        # NON-ROOT WIDGET PATH (no else needed)
        # ---------------------------------------------------------
        if parent == 0:
            raise ValueError(f"Non-root widget {wid} cannot have parent=0")

        parent_wid = XPWidgetID(parent)
        parent_info = self._get_widget(parent_wid)
        window_info = parent_info.window

        # Create widget
        info = WidgetInfo(
            wid=wid,
            widget_class=widget_class,
            window=window_info,
            parent=parent_wid,
            _geometry=(left, top, right, bottom),
            _descriptor=descriptor,
            _visible=bool(visible),
        )

        if widget_class == self.fake_xp.WidgetClass_TextField:
            info.edit_buffer = descriptor

        # Register + link to parent
        window_info.widgets[wid] = info
        parent_info.children.append(wid)
        window_info._dirty_xp_to_dpg = True

        return wid

    def _create_window_for_root_geometry(self, left, top, right, bottom) -> WindowExInfo:
        win_id = self.fake_xp.createWindowEx(
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            decoration=self.fake_xp.WindowDecorationRoundRectangle,
            layer=self.fake_xp.WindowLayerFloatingWindows,
        )
        return self.fake_xp.window_manager.require_info(win_id)

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
    def setWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID | int, value: Any) -> None:
        info = self._require_widget(wid)
        self._update_widget(info, prop=(prop, value))

    def getWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID | int) -> Any:
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
        msg: XPWidgetMessage | int,
        param1: Any,
        param2: Any,
    ) -> None:

        current = wid
        visited: set[XPWidgetID] = set()

        while current and current not in visited:
            visited.add(current)
            info = self._require_widget(current)

            # XP semantics: callbacks return int
            #   0 → continue bubbling
            #   non-zero → stop bubbling
            for cb in info.callbacks:
                try:
                    result = cb(current, msg, param1, param2)
                except Exception:
                    result = 0

                if result:
                    self._widgets_dirty = True
                    return

            current = info.parent

        self._widgets_dirty = True

    def broadcastMessageToWidget(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage | int,
        param1: Any,
        param2: Any,
    ) -> None:

        visited: set[XPWidgetID] = set()

        def _broadcast(current: XPWidgetID) -> bool:
            # Returns True if bubbling should STOP
            if current in visited:
                return False
            visited.add(current)

            info = self._require_widget(current)

            # Deliver to this widget first
            for cb in info.callbacks:
                try:
                    result = cb(current, msg, param1, param2)
                except Exception:
                    result = 0

                # XP semantics: non-zero return stops propagation
                if result:
                    return True

            # Then deliver to children
            for child in info.children:
                if _broadcast(child):
                    return True

            return False

        _broadcast(wid)
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

    def _require_widget(self, wid: XPWidgetID) -> WidgetInfo:
        """
        Return the WidgetInfo for the given XPWidgetID.

        Widgets are now stored inside their owning WindowExInfo instance, not in a
        global registry. This method searches all WindowEx objects and returns the
        authoritative WidgetInfo. If the widget does not exist, a fail-fast error
        is raised.
        """

        for win in self.fake_xp.window_manager.all_info():
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
