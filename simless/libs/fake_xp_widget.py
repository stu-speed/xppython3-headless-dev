# ===========================================================================
# FakeXPWidgets — DearPyGui-backed XPWidget emulator (prod-compatible)
#
# Strong typing via xp_typing, safe symbol-level imports, and full compatibility
# with real XPPython3 (no nonexistent symbols). All widget constants/messages/
# properties are accessed dynamically through XPPython3.xp to avoid importing
# the stub xp.py (which imports XPLMCamera and crashes in simless mode).
# ===========================================================================

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

import dearpygui.dearpygui as dpg

import XPPython3
from XPPython3.xp_typing import (
    XPWidgetID,
    XPWidgetClass,
    XPWidgetPropertyID,
    XPWidgetMessage,
    XPWidgetGeometry,
)
if TYPE_CHECKING:
    from simless.libs.fake_xp.fakexp import FakeXP

XPWidgetCallback = Callable[[int, int, Any, Any], int]
WidgetCallback = XPWidgetCallback
WidgetGeometry = XPWidgetGeometry


class FakeXPWidgets:
    def __init__(self, xp: FakeXP) -> None:
        self.xp = xp

        self._widgets: Dict[int, Dict[str, Any]] = {}
        self._callbacks: Dict[int, List[WidgetCallback]] = {}
        self._next_id: int = 1

        self._parent: Dict[int, int] = {}
        self._descriptor: Dict[int, str] = {}
        self._classes: Dict[int, XPWidgetClass] = {}
        self._dpg_ids: Dict[int, int] = {}

        self._z_order: List[int] = []
        self._default_main_window: Optional[int] = None
        self._focused_widget: Optional[int] = None

    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if getattr(self.xp, "debug_enabled", False):
            print(f"[FakeXPWidgets] {msg}")

    # ----------------------------------------------------------------------
    # CREATE / DESTROY
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
        parent: int,
        widget_class: XPWidgetClass,
    ) -> XPWidgetID:

        wid = self._next_id
        self._next_id += 1

        x = left
        y = top
        w = right - left
        h = top - bottom

        self._widgets[wid] = {
            "geometry": (x, y, w, h),
            "properties": {},
            "visible": bool(visible),
        }

        self._parent[wid] = parent
        self._descriptor[wid] = descriptor
        self._classes[wid] = widget_class
        self._z_order.append(wid)

        return XPWidgetID(wid)

    def killWidget(self, wid: XPWidgetID) -> None:
        self._widgets.pop(wid, None)
        self._callbacks.pop(wid, None)
        self._parent.pop(wid, None)
        self._descriptor.pop(wid, None)
        self._classes.pop(wid, None)

        dpg_id = self._dpg_ids.pop(wid, None)
        if dpg_id is not None and dpg.does_item_exist(dpg_id):
            dpg.delete_item(dpg_id)

        if wid in self._z_order:
            self._z_order.remove(wid)

        if self._focused_widget == wid:
            self._focused_widget = None

    # ----------------------------------------------------------------------
    # GEOMETRY
    # ----------------------------------------------------------------------
    def setWidgetGeometry(self, wid: XPWidgetID, x: int, y: int, w: int, h: int) -> None:
        if wid in self._widgets:
            self._widgets[wid]["geometry"] = (x, y, w, h)
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], pos=(x, y), width=w, height=h)

    def getWidgetGeometry(self, wid: XPWidgetID) -> WidgetGeometry:
        return self._widgets.get(wid, {}).get("geometry", (0, 0, 0, 0))

    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> WidgetGeometry:
        return self.getWidgetGeometry(wid)

    # ----------------------------------------------------------------------
    # VISIBILITY
    # ----------------------------------------------------------------------
    def showWidget(self, wid: XPWidgetID) -> None:
        if wid in self._widgets:
            self._widgets[wid]["visible"] = True
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], show=True)

    def hideWidget(self, wid: XPWidgetID) -> None:
        if wid in self._widgets:
            self._widgets[wid]["visible"] = False
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], show=False)

    def isWidgetVisible(self, wid: XPWidgetID) -> bool:
        return bool(self._widgets.get(wid, {}).get("visible", False))

    # ----------------------------------------------------------------------
    # Z‑ORDER
    # ----------------------------------------------------------------------
    def isWidgetInFront(self, wid: XPWidgetID) -> bool:
        return self._z_order and self._z_order[-1] == wid

    def bringWidgetToFront(self, wid: XPWidgetID) -> None:
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.append(wid)

    def pushWidgetBehind(self, wid: XPWidgetID) -> None:
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)

    # ----------------------------------------------------------------------
    # PARENT / CLASS / DESCRIPTOR
    # ----------------------------------------------------------------------
    def getParentWidget(self, wid: XPWidgetID) -> XPWidgetID:
        return XPWidgetID(self._parent.get(wid, 0))

    def getWidgetClass(self, wid: XPWidgetID) -> XPWidgetClass:
        xp = XPPython3.xp
        return self._classes.get(wid, xp.WidgetClass_GeneralGraphics)

    def getWidgetUnderlyingWindow(self, wid: XPWidgetID) -> int:
        return 0

    def setWidgetDescriptor(self, wid: XPWidgetID, text: str) -> None:
        self._descriptor[wid] = text

        if wid in self._dpg_ids:
            dpg_id = self._dpg_ids[wid]
            dpg.set_value(dpg_id, text)
            dpg.configure_item(dpg_id, default_value=text)

    def getWidgetDescriptor(self, wid: XPWidgetID) -> str:
        return self._descriptor.get(wid, "")

    # ----------------------------------------------------------------------
    # PROPERTIES
    # ----------------------------------------------------------------------
    def setWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID, value: Any) -> None:
        xp = XPPython3.xp

        if wid not in self._widgets:
            return

        self._widgets[wid]["properties"][prop] = value

        if wid in self._dpg_ids:
            dpg_id = self._dpg_ids[wid]

            if prop == xp.Property_ScrollBarMin:
                dpg.configure_item(dpg_id, min_value=int(value))

            elif prop == xp.Property_ScrollBarMax:
                dpg.configure_item(dpg_id, max_value=int(value))

            elif prop == xp.Property_ScrollBarSliderPosition:
                dpg.set_value(dpg_id, int(value))

    def getWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID) -> Any:
        return self._widgets.get(wid, {}).get("properties", {}).get(prop)

    # ----------------------------------------------------------------------
    # CALLBACKS + MESSAGE DISPATCH
    # ----------------------------------------------------------------------
    def addWidgetCallback(self, wid: XPWidgetID, callback: WidgetCallback) -> None:
        self._callbacks.setdefault(wid, []).append(callback)

    def sendWidgetMessage(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage,
        param1: Any,
        param2: Any,
    ) -> None:

        current = wid
        visited = set()

        while current and current not in visited:
            visited.add(current)
            for cb in self._callbacks.get(current, []):
                try:
                    cb(msg, current, param1, param2)
                except Exception as exc:
                    self.xp.log(f"  callback error in {cb.__name__}: {exc!r}")
            current = self._parent.get(current, 0)

    # ----------------------------------------------------------------------
    # HIT TEST
    # ----------------------------------------------------------------------
    def getWidgetForLocation(self, x: int, y: int) -> Optional[XPWidgetID]:
        for wid in reversed(self._z_order):
            w = self._widgets.get(wid)
            if not w or not w["visible"]:
                continue
            gx, gy, gw, gh = w["geometry"]
            if gx <= x <= gx + gw and gy <= y <= gy + gh:
                return XPWidgetID(wid)
        return None

    # ----------------------------------------------------------------------
    # KEYBOARD FOCUS
    # ----------------------------------------------------------------------
    def setKeyboardFocus(self, wid: XPWidgetID) -> None:
        self._focused_widget = wid

    def loseKeyboardFocus(self, wid: XPWidgetID) -> None:
        if self._focused_widget == wid:
            self._focused_widget = None

    # ----------------------------------------------------------------------
    # PARENT RESOLUTION
    # ----------------------------------------------------------------------
    def _resolve_dpg_parent(self, wid: XPWidgetID) -> int:
        xp = XPPython3.xp
        parent = self._parent.get(wid, 0)
        wclass = self._classes.get(wid)

        if wclass == xp.WidgetClass_MainWindow:
            return 0

        if parent == 0:
            if self._default_main_window is None:
                self._default_main_window = dpg.add_window(label="FakeXP Default Window")
            return self._default_main_window

        if parent not in self._dpg_ids:
            self._ensure_dpg_item_for_widget(parent)

        return self._dpg_ids[parent]

    # ----------------------------------------------------------------------
    # DPG CREATION
    # ----------------------------------------------------------------------
    def _ensure_dpg_item_for_widget(self, wid: XPWidgetID) -> None:
        xp = XPPython3.xp

        if wid in self._dpg_ids:
            dpg_id = self._dpg_ids[wid]
            if dpg.is_item_ok(dpg_id):
                return
            self._dpg_ids.pop(wid)

        wclass = self._classes[wid]
        desc = self._descriptor[wid]
        x, y, w, h = self._widgets[wid]["geometry"]

        parent = self._resolve_dpg_parent(wid)

        if wclass == xp.WidgetClass_MainWindow:
            dpg_id = dpg.add_window(label=desc or "Window", pos=(x, y), width=w, height=h)

        elif wclass == xp.WidgetClass_Caption:
            dpg_id = dpg.add_text(default_value=desc or "", parent=parent)

        elif wclass == xp.WidgetClass_ScrollBar:
            min_v = self.getWidgetProperty(wid, xp.Property_ScrollBarMin) or 0
            max_v = self.getWidgetProperty(wid, xp.Property_ScrollBarMax) or 100
            cur_v = self.getWidgetProperty(wid, xp.Property_ScrollBarSliderPosition) or min_v

            def _on_slider(sender, app_data, user_data):
                self.setWidgetProperty(user_data, xp.Property_ScrollBarSliderPosition, int(app_data))
                self.sendWidgetMessage(user_data, xp.Msg_ScrollBarSliderPositionChanged, user_data, None)

            dpg_id = dpg.add_slider_int(
                label=desc or "Slider",
                min_value=int(min_v),
                max_value=int(max_v),
                default_value=int(cur_v),
                width=w,
                parent=parent,
                callback=_on_slider,
                user_data=wid,
            )

        elif wclass == xp.WidgetClass_Button:
            def _on_button(sender, app_data, user_data):
                self.sendWidgetMessage(user_data, xp.Msg_PushButtonPressed, user_data, None)

            dpg_id = dpg.add_button(
                label=desc or "Button",
                width=w,
                height=h,
                parent=parent,
                callback=_on_button,
                user_data=wid,
            )

        else:
            dpg_id = dpg.add_text(desc or f"Widget {wid}", parent=parent)

        self._dpg_ids[wid] = dpg_id

    # ----------------------------------------------------------------------
    # RENDER
    # ----------------------------------------------------------------------
    def _render_widgets(self) -> None:
        for wid in self._widgets.keys():
            self._ensure_dpg_item_for_widget(wid)

    def _draw_all_widgets(self) -> None:
        self._render_widgets()
