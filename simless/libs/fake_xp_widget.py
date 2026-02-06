# ===========================================================================
# FakeXPWidgets — DearPyGui-backed XPWidget emulator (prod-compatible)
# ===========================================================================

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Tuple

import dearpygui.dearpygui as dpg

WidgetHandle = int
WidgetGeometry = Tuple[int, int, int, int]
WidgetCallback = Callable[[int, int, Any, Any], None]

# Widget classes
xpWidgetClass_MainWindow = 1
xpWidgetClass_SubWindow = 2
xpWidgetClass_Button = 3
xpWidgetClass_TextField = 4
xpWidgetClass_Caption = 5
xpWidgetClass_ScrollBar = 6
xpWidgetClass_ListBox = 7
xpWidgetClass_Custom = 99

# Properties
Property_MainWindowType = 1000
Property_MainWindowHasCloseBoxes = 1100
Property_MainWindowIsCloseBox = 1101
Property_MainWindowIsResizable = 1102

Property_ScrollBarMin = 110
Property_ScrollBarMax = 111
Property_ScrollBarSliderPosition = 112

Property_ListItems = 2101
Property_ListSelection = 2102

# Messages
ScrollBarTypeScrollBar = 0
ScrollBarTypeSlider = 1

Msg_ScrollBarSliderPositionChanged = 13
Message_CloseButtonPushed = 1
Msg_MouseDown = 6
Msg_MouseDrag = 8
Msg_MouseUp = 7
Msg_KeyPress = 12
Msg_PushButtonPressed = 14


class FakeXPWidgets:
    def __init__(self, fakexp) -> None:
        self.xp = fakexp

        self._widgets: Dict[int, Dict[str, Any]] = {}
        self._callbacks: Dict[int, List[WidgetCallback]] = {}
        self._next_id = 1

        self._parent: Dict[int, int] = {}
        self._descriptor: Dict[int, str] = {}
        self._classes: Dict[int, int] = {}
        self._dpg_ids: Dict[int, int] = {}

        self._z_order: List[int] = []
        self._default_main_window: Optional[int] = None
        self._focused_widget: Optional[int] = None

    # ------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if getattr(self.xp, "debug_enabled", False):
            print(f"[FakeXPWidgets] {msg}")

    # ------------------------------------------------------------------
    # CREATE / DESTROY
    # ------------------------------------------------------------------
    def createWidget(self, left, top, right, bottom, visible, descriptor, is_root, parent, widget_class):
        wid = self._next_id
        self._next_id += 1

        x = left
        y = top
        w = right - left
        h = top - bottom

        self._dbg(f"CREATE wid={wid} class={widget_class} desc={descriptor!r} geom={(x,y,w,h)} parent={parent}")

        self._widgets[wid] = {
            "geometry": (x, y, w, h),
            "properties": {},
            "visible": bool(visible),
        }

        self._parent[wid] = parent
        self._descriptor[wid] = descriptor
        self._classes[wid] = widget_class
        self._z_order.append(wid)

        return wid

    def killWidget(self, wid):
        self._dbg(f"KILL wid={wid}")

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

    # ------------------------------------------------------------------
    # GEOMETRY
    # ------------------------------------------------------------------
    def setWidgetGeometry(self, wid, x, y, w, h):
        self._dbg(f"SET GEOMETRY wid={wid} → {(x,y,w,h)}")
        if wid in self._widgets:
            self._widgets[wid]["geometry"] = (x, y, w, h)
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], pos=(x, y), width=w, height=h)

    def getWidgetGeometry(self, wid):
        return self._widgets.get(wid, {}).get("geometry", (0, 0, 0, 0))

    def getWidgetExposedGeometry(self, wid):
        return self.getWidgetGeometry(wid)

    # ------------------------------------------------------------------
    # VISIBILITY
    # ------------------------------------------------------------------
    def showWidget(self, wid):
        self._dbg(f"SHOW wid={wid}")
        if wid in self._widgets:
            self._widgets[wid]["visible"] = True
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], show=True)

    def hideWidget(self, wid):
        self._dbg(f"HIDE wid={wid}")
        if wid in self._widgets:
            self._widgets[wid]["visible"] = False
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], show=False)

    def isWidgetVisible(self, wid):
        return bool(self._widgets.get(wid, {}).get("visible", False))

    # ------------------------------------------------------------------
    # Z‑ORDER
    # ------------------------------------------------------------------
    def isWidgetInFront(self, wid):
        return self._z_order and self._z_order[-1] == wid

    def bringWidgetToFront(self, wid):
        self._dbg(f"BRING FRONT wid={wid}")
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.append(wid)

    def pushWidgetBehind(self, wid):
        self._dbg(f"PUSH BEHIND wid={wid}")
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)

    # ------------------------------------------------------------------
    # PARENT / CLASS / DESCRIPTOR
    # ------------------------------------------------------------------
    def getParentWidget(self, wid):
        return self._parent.get(wid, 0)

    def getWidgetClass(self, wid):
        return self._classes.get(wid, xpWidgetClass_Custom)

    def getWidgetUnderlyingWindow(self, wid):
        return 0

    def setWidgetDescriptor(self, wid, text):
        self._dbg(f"SET DESCRIPTOR wid={wid} text={text!r}")
        self._descriptor[wid] = text

        if wid in self._dpg_ids:
            dpg_id = self._dpg_ids[wid]
            dpg.set_value(dpg_id, text)
            dpg.configure_item(dpg_id, default_value=text)

    def getWidgetDescriptor(self, wid):
        return self._descriptor.get(wid, "")

    # ------------------------------------------------------------------
    # PROPERTIES
    # ------------------------------------------------------------------
    def setWidgetProperty(self, wid, prop, value):
        self._dbg(f"SET PROPERTY wid={wid} prop={prop} value={value}")
        if wid not in self._widgets:
            return

        self._widgets[wid]["properties"][prop] = value

        if wid in self._dpg_ids:
            dpg_id = self._dpg_ids[wid]

            if prop == Property_ScrollBarMin:
                dpg.configure_item(dpg_id, min_value=int(value))

            elif prop == Property_ScrollBarMax:
                dpg.configure_item(dpg_id, max_value=int(value))

            elif prop == Property_ScrollBarSliderPosition:
                dpg.set_value(dpg_id, int(value))

    def getWidgetProperty(self, wid, prop):
        return self._widgets.get(wid, {}).get("properties", {}).get(prop)

    # ------------------------------------------------------------------
    # CALLBACKS + MESSAGE DISPATCH (prod plugin expects: handler(msg, widget,...))
    # ------------------------------------------------------------------
    def addWidgetCallback(self, wid, callback):
        self._dbg(f"ADD CALLBACK wid={wid}")
        self._callbacks.setdefault(wid, []).append(callback)

    def sendWidgetMessage(self, wid, msg, param1, param2):
        self._dbg(f"SEND MSG wid={wid} msg={msg} param1={param1} param2={param2}")

        # Bubble to widget and all ancestors, calling as (msg, widget, ...)
        current = wid
        visited = set()

        while current and current not in visited:
            visited.add(current)
            self._dbg(f" → dispatching to wid={current}")
            for cb in self._callbacks.get(current, []):
                try:
                    cb(msg, current, param1, param2)
                except Exception as e:
                    self._dbg(f"  callback error in {cb.__name__}: {e!r}")
            current = self._parent.get(current, 0)

    # ------------------------------------------------------------------
    # HIT TEST
    # ------------------------------------------------------------------
    def getWidgetForLocation(self, x, y):
        for wid in reversed(self._z_order):
            w = self._widgets.get(wid)
            if not w or not w["visible"]:
                continue
            gx, gy, gw, gh = w["geometry"]
            if gx <= x <= gx + gw and gy <= y <= gy + gh:
                self._dbg(f"HIT wid={wid}")
                return wid
        self._dbg("HIT none")
        return None

    # ------------------------------------------------------------------
    # KEYBOARD FOCUS
    # ------------------------------------------------------------------
    def setKeyboardFocus(self, wid):
        self._dbg(f"FOCUS wid={wid}")
        self._focused_widget = wid

    def loseKeyboardFocus(self, wid):
        if self._focused_widget == wid:
            self._dbg(f"LOSE FOCUS wid={wid}")
            self._focused_widget = None

    # ------------------------------------------------------------------
    # PARENT RESOLUTION
    # ------------------------------------------------------------------
    def _resolve_dpg_parent(self, wid):
        parent = self._parent.get(wid, 0)
        wclass = self._classes.get(wid)

        self._dbg(f"RESOLVE PARENT wid={wid} class={wclass} xp_parent={parent}")

        if wclass == xpWidgetClass_MainWindow:
            return 0

        if parent == 0:
            if self._default_main_window is None:
                self._default_main_window = dpg.add_window(label="FakeXP Default Window")
            return self._default_main_window

        if parent not in self._dpg_ids:
            self._ensure_dpg_item_for_widget(parent)

        return self._dpg_ids[parent]

    # ------------------------------------------------------------------
    # DPG CREATION
    # ------------------------------------------------------------------
    def _ensure_dpg_item_for_widget(self, wid):
        if wid in self._dpg_ids:
            dpg_id = self._dpg_ids[wid]
            if dpg.is_item_ok(dpg_id):
                return
            self._dpg_ids.pop(wid)

        wclass = self._classes[wid]
        desc = self._descriptor[wid]
        x, y, w, h = self._widgets[wid]["geometry"]

        parent = self._resolve_dpg_parent(wid)

        if wclass == xpWidgetClass_MainWindow:
            dpg_id = dpg.add_window(label=desc or "Window", pos=(x, y), width=w, height=h)

        elif wclass == xpWidgetClass_Caption:
            dpg_id = dpg.add_text(default_value=desc or "", parent=parent)

        elif wclass == xpWidgetClass_ScrollBar:
            min_v = self.getWidgetProperty(wid, Property_ScrollBarMin) or 0
            max_v = self.getWidgetProperty(wid, Property_ScrollBarMax) or 100
            cur_v = self.getWidgetProperty(wid, Property_ScrollBarSliderPosition) or min_v

            def _on_slider(sender, app_data, user_data):
                self.setWidgetProperty(user_data, Property_ScrollBarSliderPosition, int(app_data))
                self.sendWidgetMessage(user_data, Msg_ScrollBarSliderPositionChanged, user_data, None)

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

        elif wclass == xpWidgetClass_Button:
            def _on_button(sender, app_data, user_data):
                self.sendWidgetMessage(user_data, Msg_PushButtonPressed, user_data, None)

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

    # ------------------------------------------------------------------
    # RENDER
    # ------------------------------------------------------------------
    def _render_widgets(self):
        for wid in self._widgets.keys():
            self._ensure_dpg_item_for_widget(wid)

    def _draw_all_widgets(self):
        self._render_widgets()
