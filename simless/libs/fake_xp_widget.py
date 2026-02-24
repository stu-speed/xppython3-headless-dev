# simless/libs/fake_xp/fake_xp_widget.py
# ===========================================================================
# FakeXPWidget — Widget subsystem mixin for FakeXP
#
# ROLE
#   Provide a deterministic, minimal, X‑Plane‑authentic widget façade for
#   simless execution. This subsystem mirrors the public xp widget API
#   surface without adding behavior, inference, or hidden state.
#
# CORE INVARIANTS
#   - Must match XPPython3 xp widget API names and signatures exactly.
#   - Must not infer semantics or perform validation; only minimal behavior.
#   - Must not introduce fields or attributes not present in real xp widgets.
#   - Must not mutate SDK‑shaped objects (XPWidgetGeometry, etc.).
#   - Must return deterministic values based solely on internal storage.
#
# SIMLESS RULES
#   - DearPyGui is used only for optional GUI visualization.
#   - DPG IDs are internal only and never exposed to plugin code.
#   - No automatic layout, no inference of widget hierarchy.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

import dearpygui.dearpygui as dpg
import XPPython3

from XPPython3.xp_typing import (
    XPWidgetID,
    XPWidgetClass,
    XPWidgetPropertyID,
    XPWidgetMessage,
)

if TYPE_CHECKING:
    from simless.libs.fake_xp_interface import FakeXPInterface
    xp: FakeXPInterface


XPWidgetCallback = Callable[[int, int, Any, Any], int]


class FakeXPWidget:
    """
    Widget subsystem mixin for FakeXP.
    FakeXP calls _init_widgets() during construction.
    """

    public_api_names = [
        "createWidget",
        "killWidget",
        "getWidgetProperty",
        "setWidgetProperty",
        "getWidgetGeometry",
        "setWidgetGeometry",
        "showWidget",
        "hideWidget",
        "isWidgetVisible",
        "sendMessageToWidget",
        "getWidgetForLocation",
        "getParentWidget",
    ]

    # ----------------------------------------------------------------------
    # INITIALIZATION
    # ----------------------------------------------------------------------
    def _init_widgets(self) -> None:
        self._widgets: Dict[XPWidgetID, Dict[str, Any]] = {}
        self._callbacks: Dict[XPWidgetID, List[XPWidgetCallback]] = {}

        self._parent: Dict[XPWidgetID, XPWidgetID] = {}
        self._descriptor: Dict[XPWidgetID, str] = {}
        self._classes: Dict[XPWidgetID, XPWidgetClass] = {}

        self._dpg_ids: Dict[XPWidgetID, int] = {}

        self._z_order: List[XPWidgetID] = []
        self._focused_widget: Optional[XPWidgetID] = None
        self._default_main_window: Optional[int] = None

        self._next_id: int = 1

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

        wid = XPWidgetID(self._next_id)
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

        self._parent[wid] = XPWidgetID(parent)
        self._descriptor[wid] = descriptor
        self._classes[wid] = widget_class
        self._z_order.append(wid)

        return wid

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
    def setWidgetGeometry(
        self,
        wid: XPWidgetID,
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> None:
        if wid in self._widgets:
            self._widgets[wid]["geometry"] = (x, y, w, h)

            if wid in self._dpg_ids:
                dpg.configure_item(
                    self._dpg_ids[wid],
                    pos=(x, y),
                    width=w,
                    height=h,
                )

    def getWidgetGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        x, y, w, h = self._widgets.get(wid, {}).get("geometry", (0, 0, 0, 0))
        return (x, y, x + w, y - h)

    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
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
        return bool(self._z_order) and self._z_order[-1] == wid

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
        return self._parent.get(wid, XPWidgetID(0))

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
    def setWidgetProperty(
        self,
        wid: XPWidgetID,
        prop: XPWidgetPropertyID,
        value: Any,
    ) -> None:
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

    def getWidgetProperty(
        self,
        wid: XPWidgetID,
        prop: XPWidgetPropertyID,
    ) -> Any:
        props = self._widgets.get(wid, {}).get("properties", {})
        return props.get(prop)

    # ----------------------------------------------------------------------
    # CALLBACKS + MESSAGE DISPATCH
    # ----------------------------------------------------------------------
    def addWidgetCallback(
        self,
        wid: XPWidgetID,
        callback: XPWidgetCallback,
    ) -> None:
        self._callbacks.setdefault(wid, []).append(callback)

    def sendMessageToWidget(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage,
        param1: Any,
        param2: Any,
    ) -> None:

        current = wid
        visited: set[XPWidgetID] = set()
        xp = XPPython3.xp

        while current and current not in visited:
            visited.add(current)
            for cb in self._callbacks.get(current, []):
                try:
                    cb(msg, int(current), param1, param2)
                except Exception as exc:
                    xp.log(f"callback error in {cb.__name__}: {exc!r}")
            current = self._parent.get(current, XPWidgetID(0))

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
                return wid
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
    # DPG PARENT RESOLUTION
    # ----------------------------------------------------------------------
    def _resolve_dpg_parent(self, wid: XPWidgetID) -> int:
        xp = XPPython3.xp
        parent = self._parent.get(wid, XPWidgetID(0))
        wclass = self._classes.get(wid)

        if wclass == xp.WidgetClass_MainWindow:
            return 0

        if parent == XPWidgetID(0):
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

        elif wclass == xp.WidgetClass_TextField:
            dpg_id = dpg.add_input_text(
                default_value=desc or "",
                width=w,
                parent=parent,
            )

        elif wclass == xp.WidgetClass_ScrollBar:
            min_v = self.getWidgetProperty(wid, xp.Property_ScrollBarMin) or 0
            max_v = self.getWidgetProperty(wid, xp.Property_ScrollBarMax) or 100
            cur_v = self.getWidgetProperty(wid, xp.Property_ScrollBarSliderPosition) or min_v

            def _on_slider(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                self.setWidgetProperty(widget_id, xp.Property_ScrollBarSliderPosition, int(app_data))
                self.sendMessageToWidget(
                    widget_id,
                    xp.Msg_ScrollBarSliderPositionChanged,
                    widget_id,
                    None,
                )

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
                widget_id = XPWidgetID(user_data)
                self.sendMessageToWidget(
                    widget_id,
                    xp.Msg_PushButtonPressed,
                    widget_id,
                    None,
                )

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
    def _dispatch_draw(self, wid: XPWidgetID) -> None:
        xp = XPPython3.xp

        if not self._widgets.get(wid, {}).get("visible", False):
            return

        for cb in self._callbacks.get(wid, []):
            try:
                cb(xp.Msg_Draw, wid, None, None)
            except Exception as exc:
                xp.log(f"[FakeXPWidget] draw callback error in {cb.__name__}: {exc!r}")

        for child, parent in self._parent.items():
            if parent == wid:
                self._dispatch_draw(child)

    def _render_widgets(self) -> None:
        for wid in list(self._widgets.keys()):
            self._ensure_dpg_item_for_widget(wid)

    def _draw_all_widgets(self) -> None:
        self._render_widgets()

        for wid in list(self._widgets.keys()):
            if self._parent.get(wid, XPWidgetID(0)) == XPWidgetID(0):
                self._dispatch_draw(wid)
