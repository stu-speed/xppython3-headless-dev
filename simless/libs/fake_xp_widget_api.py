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
#   - All state mutations mark _needs_redraw
#
# This mixin is intended to be combined with a concrete backend that owns:
#   - self._widgets : Dict[XPWidgetID, WidgetInfo]
#   - self._z_order : List[XPWidgetID]
#   - self._needs_redraw : bool
#   - self._require_widget(wid)
#
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from simless.libs.fake_xp_interface import FakeXPInterface
from simless.libs.fake_xp_types import WidgetInfo
from XPPython3.xp_typing import XPWidgetClass, XPWidgetID, XPWidgetMessage, XPWidgetPropertyID

XPWidgetCallback = Callable[[int, int, Any, Any], int]


class FakeXPWidgetsAPI:
    xp: FakeXPInterface

    _widgets: Dict[XPWidgetID, WidgetInfo]
    _z_order: List[XPWidgetID]
    _needs_redraw: bool
    _focused_widget: Optional[XPWidgetID]
    _next_id: int
    _widgets_initialized: bool

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
        wid = XPWidgetID(self._next_id)
        self._next_id += 1

        info = WidgetInfo(
            wid=wid,
            widget_class=widget_class,
            parent=XPWidgetID(parent),
            descriptor=descriptor,
            geometry=(left, top, right, bottom),
            visible=bool(visible),
        )

        if widget_class == self.xp.WidgetClass_TextField:
            info.edit_buffer = descriptor

        self._widgets[wid] = info
        self._z_order.append(wid)
        self._needs_redraw = True

        return wid

    def killWidget(self, wid: XPWidgetID) -> None:
        info = self._widgets.pop(wid, None)
        if info is None:
            return

        for child in self._widgets.values():
            if child.parent == wid:
                child.parent = XPWidgetID(0)

        if info.dpg_id is not None:
            self.xp.dpg_delete_item(info.dpg_id)

        info.dpg_id = None
        info.container_id = None

        if wid in self._z_order:
            self._z_order.remove(wid)

        if self._focused_widget == wid:
            self._focused_widget = None

        self._needs_redraw = True

    def destroyWidget(self, wid: XPWidgetID, destroy_children: int = 1) -> None:
        if destroy_children:
            children = [
                w for w, info in self._widgets.items()
                if info.parent == wid
            ]
            for child in children:
                self.destroyWidget(child, destroy_children=1)

        self.killWidget(wid)

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
        """
        Set widget geometry in global XP screen coordinates.

        Geometry is stored as (left, top, right, bottom).
        """
        info = self._require_widget(wid)

        info.geometry = (left, top, right, bottom)

        # Invalidate backend-applied geometry
        info.geom_applied = False
        info.container_geom_applied = None

        self._needs_redraw = True

    def getWidgetGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        """
        Return widget geometry as (left, top, right, bottom),
        matching XPPython3 behavior.
        """
        info = self._require_widget(wid)
        return info.geometry

    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        """
        XPWidgets exposes the same geometry as getWidgetGeometry().
        """
        return self.getWidgetGeometry(wid)

    # ------------------------------------------------------------------
    # VISIBILITY
    # ------------------------------------------------------------------

    def showWidget(self, wid: XPWidgetID) -> None:
        info = self._require_widget(wid)
        info.visible = True
        if info.container_id is not None:
            self.xp.dpg_show_item(info.container_id)
        self._needs_redraw = True

    def hideWidget(self, wid: XPWidgetID) -> None:
        info = self._require_widget(wid)
        info.visible = False
        if info.container_id is not None:
            self.xp.dpg_hide_item(info.container_id)
        self._needs_redraw = True

    def isWidgetVisible(self, wid: XPWidgetID) -> bool:
        return bool(self._require_widget(wid).visible)

    # ------------------------------------------------------------------
    # PROPERTIES
    # ------------------------------------------------------------------

    def setWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID, value: Any) -> None:
        info = self._require_widget(wid)
        info.properties[prop] = value
        self._needs_redraw = True

        if info.widget_class == self.xp.WidgetClass_ScrollBar and info.dpg_id is not None:
            if prop == self.xp.Property_ScrollBarMin:
                self.xp.dpg_configure_item(info.dpg_id, min_value=int(value))
            elif prop == self.xp.Property_ScrollBarMax:
                self.xp.dpg_configure_item(info.dpg_id, max_value=int(value))
            elif prop == self.xp.Property_ScrollBarSliderPosition:
                self._fakexp_scrollbar_set_position(wid, value)

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
        """
        Send a message to an XPWidget and bubble it up the parent chain.

        XPWidgets message delivery is hierarchical: the message is delivered
        to the target widget, then to its parent, and so on until the root.

        The `widget` argument passed to callbacks is always the originating
        widget ID, matching production X-Plane behavior.
        """
        origin = wid
        current = wid
        visited: set[XPWidgetID] = set()

        while current and current not in visited:
            visited.add(current)

            info = self._require_widget(current)

            for cb in info.callbacks:
                cb(msg, origin, param1, param2)

            current = info.parent

        self._needs_redraw = True

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
            self._needs_redraw = True

    def pushWidgetBehind(self, wid: XPWidgetID) -> None:
        self._require_widget(wid)
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)
            self._needs_redraw = True

    # ------------------------------------------------------------------
    # KEYBOARD FOCUS
    # ------------------------------------------------------------------

    def getKeyboardFocus(self) -> XPWidgetID | None:
        return self._focused_widget

    def setKeyboardFocus(self, wid: XPWidgetID) -> None:
        self._require_widget(wid)
        self._focused_widget = wid
        self._needs_redraw = True

    def loseKeyboardFocus(self, wid: XPWidgetID) -> None:
        self._require_widget(wid)
        if self._focused_widget == wid:
            self._focused_widget = None
            self._needs_redraw = True

    # ------------------------------------------------------------------
    # DESCRIPTOR / CLASS
    # ------------------------------------------------------------------

    def getWidgetDescriptor(self, wid: XPWidgetID) -> str:
        return self._require_widget(wid).descriptor

    def setWidgetDescriptor(self, wid: XPWidgetID, text: str) -> None:
        info = self._require_widget(wid)
        info.descriptor = text
        self._needs_redraw = True

        if info.dpg_id is None:
            return

        if info.widget_class == self.xp.WidgetClass_TextField:
            self.xp.dpg_set_value(info.dpg_id, text.strip())
        elif info.widget_class == self.xp.WidgetClass_Caption:
            self.xp.dpg_set_value(info.dpg_id, text)
        elif info.widget_class == self.xp.WidgetClass_Button:
            self.xp.dpg_configure_item(info.dpg_id, label=text)

    def getWidgetClass(self, wid: XPWidgetID) -> XPWidgetClass:
        return self._require_widget(wid).widget_class

    def getWidgetUnderlyingWindow(self, wid: XPWidgetID) -> int:
        self._require_widget(wid)
        return 0

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    def _require_widget(self, wid: XPWidgetID) -> WidgetInfo:
        info = self._widgets.get(wid)
        if info is None:
            raise RuntimeError(f"XPWidget {wid} does not exist")
        return info

    def _fakexp_scrollbar_set_position(self, wid: XPWidgetID, value: Any) -> None:
        """
        Real‑SDK‑accurate scrollbar position setter.

        This method is expected to exist in the original file. This implementation
        preserves semantics:
        - Store the position in the widget property.
        - If a DPG slider exists, update it (write-only).
        """
        info = self._require_widget(wid)
        info.properties[self.xp.Property_ScrollBarSliderPosition] = int(value)
        self._needs_redraw = True

        if info.dpg_id is None:
            return None

        self.xp.dpg_set_value(info.dpg_id, int(value))
        return None

    def _is_widget_effectively_visible(self, wid: XPWidgetID) -> bool:
        current = wid
        while current:
            info = self._require_widget(current)
            if info is None or not info.visible:
                return False
            current = info.parent
        return True
