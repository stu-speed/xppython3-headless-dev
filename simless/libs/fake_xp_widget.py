# simless/libs/fake_xp_widget.py
# ===========================================================================
# FakeXPWidgets — strongly typed DearPyGui-backed widget emulation
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple


# ---------------------------------------------------------------------------
# Widget class constants (mirroring X-Plane)
# ---------------------------------------------------------------------------
xpWidgetClass_MainWindow = 1
xpWidgetClass_SubWindow = 2
xpWidgetClass_Button = 3
xpWidgetClass_TextField = 4
xpWidgetClass_Caption = 5
xpWidgetClass_ScrollBar = 6
xpWidgetClass_ListBox = 7
xpWidgetClass_Custom = 8

# ---------------------------------------------------------------------------
# Widget property constants
# ---------------------------------------------------------------------------
Property_ScrollValue = 2001
Property_ScrollMin = 2002
Property_ScrollMax = 2003
Property_ListItems = 2004
Property_ListSelection = 2005

# ---------------------------------------------------------------------------
# Widget message constants
# ---------------------------------------------------------------------------
Msg_MouseDown = 3001
Msg_MouseDrag = 3002
Msg_MouseUp = 3003
Msg_KeyPress = 3004


# ---------------------------------------------------------------------------
# Widget handle + info
# ---------------------------------------------------------------------------

WidgetHandle = int


@dataclass(slots=True)
class FakeWidget:
    wid: WidgetHandle
    widget_class: int
    descriptor: str
    parent: Optional[WidgetHandle]
    visible: bool
    geometry: Tuple[int, int, int, int]
    properties: Dict[int, Any]
    callbacks: List[Callable[[int, int, Any, Any], Any]]


# ---------------------------------------------------------------------------
# FakeXPWidgets implementation
# ---------------------------------------------------------------------------

class FakeXPWidgets:
    def __init__(self, xp) -> None:
        self.xp = xp
        self._widgets: Dict[WidgetHandle, FakeWidget] = {}
        self._next_wid: int = 1

    # ----------------------------------------------------------------------
    # Widget creation
    # ----------------------------------------------------------------------
    def createWidget(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        visible: int,
        descriptor: str,
        is_root: int,
        container: int,
        widget_class: int,
    ) -> WidgetHandle:
        wid = self._next_wid
        self._next_wid += 1

        widget = FakeWidget(
            wid=wid,
            widget_class=widget_class,
            descriptor=descriptor,
            parent=container if container != 0 else None,
            visible=bool(visible),
            geometry=(left, top, right, bottom),
            properties={},
            callbacks=[],
        )
        self._widgets[wid] = widget

        if hasattr(self.xp, "_dbg"):
            self.xp._dbg(
                f"createWidget: wid={wid}, class={widget_class}, desc='{descriptor}', "
                f"parent={container}, geom=({left}, {top}, {right-left}, {top-bottom})"
            )  # type: ignore

        return wid

    def createCustomWidget(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        visible: int,
        descriptor: str,
        is_root: int,
        container: int,
        callback: Callable[[int, int, Any, Any], Any],
    ) -> WidgetHandle:
        wid = self.createWidget(
            left, top, right, bottom, visible, descriptor, is_root, container, xpWidgetClass_Custom
        )
        self.addWidgetCallback(wid, callback)
        return wid

    # ----------------------------------------------------------------------
    # Widget destruction
    # ----------------------------------------------------------------------
    def killWidget(self, wid: WidgetHandle) -> None:
        if wid in self._widgets:
            del self._widgets[wid]
            if hasattr(self.xp, "_dbg"):
                self.xp._dbg(f"killWidget: wid={wid}")  # type: ignore

    # ----------------------------------------------------------------------
    # Geometry
    # ----------------------------------------------------------------------
    def setWidgetGeometry(
        self, wid: WidgetHandle, left: int, top: int, right: int, bottom: int
    ) -> None:
        widget = self._widgets.get(wid)
        if widget:
            widget.geometry = (left, top, right, bottom)

    def getWidgetGeometry(self, wid: WidgetHandle) -> Tuple[int, int, int, int]:
        widget = self._widgets.get(wid)
        return widget.geometry if widget else (0, 0, 0, 0)

    def getWidgetExposedGeometry(self, wid: WidgetHandle) -> Tuple[int, int, int, int]:
        return self.getWidgetGeometry(wid)

    # ----------------------------------------------------------------------
    # Visibility
    # ----------------------------------------------------------------------
    def showWidget(self, wid: WidgetHandle) -> None:
        widget = self._widgets.get(wid)
        if widget:
            widget.visible = True

    def hideWidget(self, wid: WidgetHandle) -> None:
        widget = self._widgets.get(wid)
        if widget:
            widget.visible = False

    def isWidgetVisible(self, wid: WidgetHandle) -> bool:
        widget = self._widgets.get(wid)
        return bool(widget.visible) if widget else False

    def isWidgetInFront(self, wid: WidgetHandle) -> bool:
        return True

    def bringWidgetToFront(self, wid: WidgetHandle) -> None:
        pass

    def pushWidgetBehind(self, wid: WidgetHandle) -> None:
        pass

    # ----------------------------------------------------------------------
    # Parent / class
    # ----------------------------------------------------------------------
    def getParentWidget(self, wid: WidgetHandle) -> Optional[WidgetHandle]:
        widget = self._widgets.get(wid)
        return widget.parent if widget else None

    def getWidgetClass(self, wid: WidgetHandle) -> int:
        widget = self._widgets.get(wid)
        return widget.widget_class if widget else 0

    def getWidgetUnderlyingWindow(self, wid: WidgetHandle) -> int:
        return 0

    # ----------------------------------------------------------------------
    # Descriptor
    # ----------------------------------------------------------------------
    def setWidgetDescriptor(self, wid: WidgetHandle, desc: str) -> None:
        widget = self._widgets.get(wid)
        if widget:
            widget.descriptor = desc

    def getWidgetDescriptor(self, wid: WidgetHandle) -> str:
        widget = self._widgets.get(wid)
        return widget.descriptor if widget else ""

    # ----------------------------------------------------------------------
    # Hit testing
    # ----------------------------------------------------------------------
    def getWidgetForLocation(self, x: int, y: int) -> Optional[WidgetHandle]:
        for wid, widget in self._widgets.items():
            left, top, right, bottom = widget.geometry
            if left <= x <= right and bottom <= y <= top:
                return wid
        return None

    # ----------------------------------------------------------------------
    # Keyboard focus
    # ----------------------------------------------------------------------
    def setKeyboardFocus(self, wid: Optional[WidgetHandle]) -> None:
        setattr(self.xp, "_keyboard_focus", wid)

    def loseKeyboardFocus(self) -> None:
        setattr(self.xp, "_keyboard_focus", None)

    # ----------------------------------------------------------------------
    # Properties
    # ----------------------------------------------------------------------
    def setWidgetProperty(self, wid: WidgetHandle, prop: int, value: Any) -> None:
        widget = self._widgets.get(wid)
        if widget:
            widget.properties[prop] = value

    def getWidgetProperty(self, wid: WidgetHandle, prop: int) -> Any:
        widget = self._widgets.get(wid)
        return widget.properties.get(prop) if widget else None

    # ----------------------------------------------------------------------
    # Callbacks
    # ----------------------------------------------------------------------
    def addWidgetCallback(
        self,
        wid: WidgetHandle,
        callback: Callable[[int, int, Any, Any], Any],
    ) -> None:
        widget = self._widgets.get(wid)
        if widget:
            widget.callbacks.append(callback)

    def sendWidgetMessage(
        self,
        wid: WidgetHandle,
        msg: int,
        param1: Any = None,
        param2: Any = None,
    ) -> None:
        widget = self._widgets.get(wid)
        if widget:
            for cb in widget.callbacks:
                try:
                    cb(wid, msg, param1, param2)
                except Exception as e:
                    if hasattr(self.xp, "_dbg"):
                        self.xp._dbg(f"Widget callback error: {e}")  # type: ignore

    # ----------------------------------------------------------------------
    # Rendering (DearPyGui-backed)
    # ----------------------------------------------------------------------
    def _draw_all_widgets(self) -> None:
        for widget in self._widgets.values():
            if not widget.visible:
                continue

            left, top, right, bottom = widget.geometry
            width = right - left
            height = top - bottom

            # Minimal DearPyGui rendering
            import dearpygui.dearpygui as dpg

            with dpg.window(
                label=widget.descriptor,
                pos=(left, bottom),
                width=width,
                height=height,
                no_title_bar=True,
                no_resize=True,
                no_move=True,
                no_close=True,
            ):
                pass
