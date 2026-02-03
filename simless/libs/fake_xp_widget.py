# ===========================================================================
# FakeXPWidgets — DearPyGui-backed XPWidget emulator
#
# Provides a lightweight, deterministic simulation of X‑Plane’s XPWidgets
# system for FakeXP. Each XP widget is represented by an integer handle and
# mapped to a corresponding DearPyGui item at runtime.
#
# Responsibilities:
#   • Maintain widget state (geometry, visibility, properties, z‑order)
#   • Create/update DearPyGui items lazily on demand
#   • Mirror XPWidget semantics: parent/child, descriptors, callbacks
#   • Provide hit‑testing, stacking, and keyboard‑focus behavior
#
# Non‑Responsibilities:
#   • DearPyGui context/viewport lifecycle (handled by FakeXPRunner)
#   • Layout management beyond explicit widget geometry
#
# Design notes:
#   • All state is stored in Python dicts for clarity and testability
#   • DPG items are cached in _dpg_ids and updated each frame
#   • Unknown widget classes fall back to simple text placeholders
#   • High‑signal debug logging is available when FakeXP.debug_enabled is True
# ===========================================================================

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Tuple

import dearpygui.dearpygui as dpg

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

WidgetHandle = int
WidgetGeometry = Tuple[int, int, int, int]  # (x, y, w, h)
WidgetProperties = Dict[int, Any]
WidgetCallback = Callable[[int, int, Any, Any], None]


# ---------------------------------------------------------------------------
# Widget classes (production-accurate names)
# ---------------------------------------------------------------------------

xpWidgetClass_MainWindow = 1
xpWidgetClass_SubWindow = 2
xpWidgetClass_Button = 3
xpWidgetClass_TextField = 4
xpWidgetClass_Caption = 5
xpWidgetClass_ScrollBar = 6
xpWidgetClass_ListBox = 7
xpWidgetClass_Custom = 99


# ---------------------------------------------------------------------------
# Widget properties (production-accurate names)
# ---------------------------------------------------------------------------

Property_ScrollValue = 2001
Property_ScrollMin = 2002
Property_ScrollMax = 2003
Property_ListItems = 2101
Property_ListSelection = 2102


# ---------------------------------------------------------------------------
# Widget messages (production parity)
# ---------------------------------------------------------------------------

Msg_MouseDown = 6
Msg_MouseDrag = 8
Msg_MouseUp = 7
Msg_KeyPress = 12


# ===========================================================================
# FakeXPWidgets — strongly typed, working version
# ===========================================================================

class FakeXPWidgets:
    """
    DearPyGui-backed XPWidget simulation layer.

    FakeXP owns the DearPyGui lifecycle. This class only creates and updates
    DPG items corresponding to XP widget definitions.
    """

    def __init__(self, fakexp) -> None:
        self.xp = fakexp

        # Core widget state
        self._widgets: Dict[WidgetHandle, Dict[str, Any]] = {}
        self._callbacks: Dict[WidgetHandle, List[WidgetCallback]] = {}
        self._next_id: int = 1

        # Parent/child relationships
        self._parent: Dict[WidgetHandle, WidgetHandle] = {}

        # Widget metadata
        self._descriptor: Dict[WidgetHandle, str] = {}
        self._classes: Dict[WidgetHandle, int] = {}
        self._dpg_ids: Dict[WidgetHandle, int] = {}

        # Focus + stacking
        self._focused_widget: Optional[int] = None
        self._z_order: List[int] = []

        # Default parent window for orphan widgets
        self._default_main_window: Optional[int] = None

    # ----------------------------------------------------------------------
    # Debug helper
    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if getattr(self.xp, "debug_enabled", False):
            print(f"[FakeXPWidgets] {msg}")

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
        parent: int,
        widget_class: int,
    ) -> WidgetHandle:

        wid = self._next_id
        self._next_id += 1

        x = left
        y = top
        w = right - left
        h = top - bottom

        self._dbg(
            f"createWidget: wid={wid}, class={widget_class}, desc={descriptor!r}, "
            f"parent={parent}, geom={(x, y, w, h)}"
        )

        self._widgets[wid] = {
            "geometry": (x, y, w, h),
            "properties": {},
            "visible": bool(visible),
        }

        self._parent[wid] = parent
        self._descriptor[wid] = descriptor
        self._classes[wid] = widget_class

        # New widgets appear on top
        self._z_order.append(wid)

        return wid

    # ----------------------------------------------------------------------
    # Widget destruction
    # ----------------------------------------------------------------------
    def killWidget(self, wid: WidgetHandle) -> None:
        self._dbg(f"killWidget: wid={wid}")

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
    # Geometry
    # ----------------------------------------------------------------------
    def setWidgetGeometry(self, wid: WidgetHandle, x: int, y: int, w: int, h: int) -> None:
        self._dbg(f"setWidgetGeometry: wid={wid}, geom={(x, y, w, h)}")
        if wid in self._widgets:
            self._widgets[wid]["geometry"] = (x, y, w, h)
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], pos=(x, y), width=w, height=h)

    def getWidgetGeometry(self, wid: WidgetHandle) -> WidgetGeometry:
        return self._widgets.get(wid, {}).get("geometry", (0, 0, 0, 0))

    def getWidgetExposedGeometry(self, wid: WidgetHandle) -> WidgetGeometry:
        return self.getWidgetGeometry(wid)

    # ----------------------------------------------------------------------
    # Visibility
    # ----------------------------------------------------------------------
    def showWidget(self, wid: WidgetHandle) -> None:
        self._dbg(f"showWidget: wid={wid}")
        if wid in self._widgets:
            self._widgets[wid]["visible"] = True
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], show=True)

    def hideWidget(self, wid: WidgetHandle) -> None:
        self._dbg(f"hideWidget: wid={wid}")
        if wid in self._widgets:
            self._widgets[wid]["visible"] = False
            if wid in self._dpg_ids:
                dpg.configure_item(self._dpg_ids[wid], show=False)

    def isWidgetVisible(self, wid: WidgetHandle) -> bool:
        return bool(self._widgets.get(wid, {}).get("visible", False))

    # ----------------------------------------------------------------------
    # Stacking order
    # ----------------------------------------------------------------------
    def isWidgetInFront(self, wid: WidgetHandle) -> bool:
        return self._z_order and self._z_order[-1] == wid

    def bringWidgetToFront(self, wid: WidgetHandle) -> None:
        self._dbg(f"bringWidgetToFront: wid={wid}")
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.append(wid)

    def pushWidgetBehind(self, wid: WidgetHandle) -> None:
        self._dbg(f"pushWidgetBehind: wid={wid}")
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)

    # ----------------------------------------------------------------------
    # Parent / class / descriptor
    # ----------------------------------------------------------------------
    def getParentWidget(self, wid: WidgetHandle) -> WidgetHandle:
        return self._parent.get(wid, 0)

    def getWidgetClass(self, wid: WidgetHandle) -> int:
        return self._classes.get(wid, xpWidgetClass_Custom)

    def getWidgetUnderlyingWindow(self, wid: WidgetHandle) -> int:
        return 0

    def setWidgetDescriptor(self, wid: WidgetHandle, text: str) -> None:
        self._dbg(f"setWidgetDescriptor: wid={wid}, text={text!r}")
        self._descriptor[wid] = text
        if wid in self._dpg_ids:
            dpg.configure_item(self._dpg_ids[wid], label=text)

    def getWidgetDescriptor(self, wid: WidgetHandle) -> str:
        return self._descriptor.get(wid, "")

    # ----------------------------------------------------------------------
    # Properties
    # ----------------------------------------------------------------------
    def setWidgetProperty(self, wid: WidgetHandle, prop: int, value: Any) -> None:
        self._dbg(f"setWidgetProperty: wid={wid}, prop={prop}, value={value}")
        if wid in self._widgets:
            self._widgets[wid]["properties"][prop] = value

    def getWidgetProperty(self, wid: WidgetHandle, prop: int) -> Any:
        return self._widgets.get(wid, {}).get("properties", {}).get(prop)

    # ----------------------------------------------------------------------
    # Callbacks + messages
    # ----------------------------------------------------------------------
    def addWidgetCallback(self, wid: WidgetHandle, callback: WidgetCallback) -> None:
        self._dbg(f"addWidgetCallback: wid={wid}")
        self._callbacks.setdefault(wid, []).append(callback)

    def sendWidgetMessage(self, wid: WidgetHandle, msg: int, param1: Any, param2: Any) -> None:
        self._dbg(f"sendWidgetMessage: wid={wid}, msg={msg}")
        for cb in self._callbacks.get(wid, []):
            try:
                cb(wid, msg, param1, param2)
            except Exception as e:
                self._dbg(f"  callback error: {e!r}")

    # ----------------------------------------------------------------------
    # Hit-testing
    # ----------------------------------------------------------------------
    def getWidgetForLocation(self, x: int, y: int) -> Optional[WidgetHandle]:
        for wid in reversed(self._z_order):
            w = self._widgets.get(wid)
            if not w or not w["visible"]:
                continue
            gx, gy, gw, gh = w["geometry"]
            if gx <= x <= gx + gw and gy <= y <= gy + gh:
                self._dbg(f"getWidgetForLocation: hit wid={wid}")
                return wid
        self._dbg("getWidgetForLocation: no hit")
        return None

    # ----------------------------------------------------------------------
    # Keyboard focus
    # ----------------------------------------------------------------------
    def setKeyboardFocus(self, wid: Optional[WidgetHandle]) -> None:
        self._dbg(f"setKeyboardFocus: wid={wid}")
        self._focused_widget = wid

    def loseKeyboardFocus(self, wid: WidgetHandle) -> None:
        if self._focused_widget == wid:
            self._dbg(f"loseKeyboardFocus: wid={wid}")
            self._focused_widget = None

    # ----------------------------------------------------------------------
    # Parent resolution
    # ----------------------------------------------------------------------
    def _resolve_dpg_parent(self, wid: WidgetHandle) -> int:
        wclass = self.getWidgetClass(wid)
        parent = self._parent.get(wid, 0)

        self._dbg(
            f"_resolve_dpg_parent: wid={wid}, class={wclass}, xp_parent={parent}"
        )

        if wclass == xpWidgetClass_MainWindow:
            return 0

        if parent == 0:
            if self._default_main_window is None:
                self._default_main_window = dpg.add_window(label="FakeXP Default Window")
            return self._default_main_window

        if parent not in self._dpg_ids:
            self._ensure_dpg_item_for_widget(parent)

        return self._dpg_ids[parent]

    # ----------------------------------------------------------------------
    # XPWidget → DPG mapping
    # ----------------------------------------------------------------------
    def _ensure_dpg_item_for_widget(self, wid: WidgetHandle) -> None:
        if wid in self._dpg_ids:
            return

        wclass = self.getWidgetClass(wid)
        desc = self.getWidgetDescriptor(wid)
        x, y, w, h = self.getWidgetGeometry(wid)

        dpg_parent = self._resolve_dpg_parent(wid)

        try:
            if wclass == xpWidgetClass_MainWindow:
                dpg_id = dpg.add_window(
                    label=desc or "Window",
                    pos=(x, y),
                    width=w,
                    height=h,
                )

            elif wclass == xpWidgetClass_Caption:
                dpg_id = dpg.add_text(desc or "", parent=dpg_parent)

            elif wclass == xpWidgetClass_ScrollBar:
                min_v = self.getWidgetProperty(wid, Property_ScrollMin) or -50
                max_v = self.getWidgetProperty(wid, Property_ScrollMax) or 50
                cur_v = self.getWidgetProperty(wid, Property_ScrollValue) or 0

                def _on_slider(sender, app_data, user_data):
                    self.setWidgetProperty(
                        user_data, Property_ScrollValue, int(app_data)
                    )
                    self.sendWidgetMessage(user_data, Msg_MouseDrag, None, None)

                dpg_id = dpg.add_slider_int(
                    label=desc or "Slider",
                    min_value=int(min_v),
                    max_value=int(max_v),
                    default_value=int(cur_v),
                    width=w,
                    parent=dpg_parent,
                    callback=_on_slider,
                    user_data=wid,
                )

            elif wclass == xpWidgetClass_Button:

                def _on_button(sender, app_data, user_data):
                    self.sendWidgetMessage(user_data, Msg_MouseDown, None, None)

                dpg_id = dpg.add_button(
                    label=desc or "Button",
                    width=w,
                    height=h,
                    parent=dpg_parent,
                    callback=_on_button,
                    user_data=wid,
                )

            else:
                dpg_id = dpg.add_text(desc or f"Widget {wid}", parent=dpg_parent)

        except Exception as e:
            self._dbg(
                f"DPG creation FAILED for wid={wid}, class={wclass}, error={e!r}"
            )
            raise

        self._dpg_ids[wid] = dpg_id

    # ----------------------------------------------------------------------
    # Rendering (passive — FakeXP drives the frame pump)
    # ----------------------------------------------------------------------
    def _render_widgets(self) -> None:
        for wid in self._widgets.keys():
            self._ensure_dpg_item_for_widget(wid)

    def _draw_all_widgets(self) -> None:
        self._render_widgets()
