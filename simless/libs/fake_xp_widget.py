# simless/libs/fake_xp/fake_xp_widget.py
# ===========================================================================
# FakeXPWidget — Widget subsystem mixin for FakeXP
#
# ROLE
#   Provide a deterministic, minimal, X‑Plane‑authentic XPWidgets façade for
#   sim‑less execution. This subsystem mirrors the public XPPython3 xp widget
#   API surface without adding behavior, inference, or hidden state.
#
# CORE DESIGN DISCOVERIES
#
#   FakeXP Widgets are anchored on an older DearPyGui (1.11.x) for one core reason:
#   it is the only version whose behavior is predictable enough to emulate X‑Plane’s
#   1990s‑era XPWidgets model without fighting the framework.
#
#   1. XPWidgets geometry is GLOBAL / SCREEN‑SPACE
#      All XPWidget geometry (including children) is expressed in global
#      screen coordinates. Parent‑relative geometry must be computed manually.
#
#   2. DearPyGui does NOT support absolute positioning of normal widgets
#      Each XP widget is wrapped in its own child_window container to allow
#      explicit positioning.
#
#   3. child_window containers MUST disable autosizing
#      autosize_x=False and autosize_y=False are required or containers
#      collapse to (0, 0) and clip their contents.
#
#   4. MainWindow geometry must be applied EXACTLY ONCE
#      Re‑applying geometry every frame causes user window moves to snap back.
#
#   5. Geometry application is deferred until layout is valid
#      XP → DPG geometry transforms occur during render, never during creation.
#
# CORE INVARIANTS
#   - Must match XPPython3 xp widget API names, signatures, and functionality.
#   - FakeXP must execute plugins with the same XPWidgets message semantics as production:
#   - Must not infer semantics or perform validation.
#   - Must not mutate SDK‑shaped objects.
#   - Geometry is applied only when XP explicitly changes it.
#
# SIMLESS RULES
#   - DearPyGui is used only for optional visualization.
#   - DPG item IDs are internal and never exposed to plugin code.
#   - No automatic layout or inferred hierarchy.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import dearpygui.dearpygui as dpg

import XPPython3
from simless.libs.fake_xp_interface import FakeXPInterface
from XPPython3.xp_typing import (XPWidgetClass, XPWidgetID, XPWidgetMessage, XPWidgetPropertyID)

XPWidgetCallback = Callable[[int, int, Any, Any], int]


class FakeXPWidget:
    xp: FakeXPInterface  # established in FakeXP

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
        "addWidgetCallback",
        "bringWidgetToFront",
        "pushWidgetBehind",
        "isWidgetInFront",
        "setKeyboardFocus",
        "loseKeyboardFocus",
        "getWidgetDescriptor",
        "setWidgetDescriptor",
        "getWidgetClass",
        "getWidgetUnderlyingWindow",
        "getWidgetExposedGeometry",
    ]

    # ------------------------------------------------------------------
    # INITIALIZATION
    # ------------------------------------------------------------------
    def _init_widgets(self) -> None:
        """Initialize all internal XPWidget bookkeeping structures."""
        self._widgets: Dict[XPWidgetID, Dict[str, Any]] = {}
        self._callbacks: Dict[XPWidgetID, List[XPWidgetCallback]] = {}
        self._parent: Dict[XPWidgetID, XPWidgetID] = {}
        self._descriptor: Dict[XPWidgetID, str] = {}
        self._classes: Dict[XPWidgetID, XPWidgetClass] = {}

        self._dpg_ids: Dict[XPWidgetID, int] = {}
        self._containers: Dict[XPWidgetID, int] = {}
        self._container_geom_applied: Dict[XPWidgetID, Tuple[int, int, int, int]] = {}

        self._main_windows: Dict[XPWidgetID, int] = {}
        self._default_main_window: Optional[int] = None

        self._z_order: List[XPWidgetID] = []
        self._focused_widget: Optional[XPWidgetID] = None
        self._edit_buffer: Dict[XPWidgetID, str] = {}

        self._layout_ready: bool = False
        self._needs_redraw: bool = True
        self._main_geometry_applied: bool = False

        self._next_id: int = 1

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
        """Create a new XPWidget and return its widget ID."""
        wid = XPWidgetID(self._next_id)
        self._next_id += 1

        self._widgets[wid] = {
            "geometry": (left, top, right - left, top - bottom),
            "properties": {},
            "visible": bool(visible),
        }
        self._parent[wid] = XPWidgetID(parent)
        self._descriptor[wid] = descriptor
        self._classes[wid] = widget_class
        self._z_order.append(wid)

        if widget_class == XPPython3.xp.WidgetClass_TextField:
            self._edit_buffer[wid] = descriptor

        self._container_geom_applied.pop(wid, None)
        self._needs_redraw = True
        return wid

    def killWidget(self, wid: XPWidgetID) -> None:
        """Destroy an XPWidget and all associated state."""
        self._widgets.pop(wid, None)
        self._callbacks.pop(wid, None)
        self._parent.pop(wid, None)
        self._descriptor.pop(wid, None)
        self._classes.pop(wid, None)
        self._edit_buffer.pop(wid, None)

        if wid in self._dpg_ids and dpg.does_item_exist(self._dpg_ids[wid]):
            dpg.delete_item(self._dpg_ids[wid])
        self._dpg_ids.pop(wid, None)

        if wid in self._containers and dpg.does_item_exist(self._containers[wid]):
            dpg.delete_item(self._containers[wid])
        self._containers.pop(wid, None)
        self._container_geom_applied.pop(wid, None)

        if wid in self._main_windows and dpg.does_item_exist(self._main_windows[wid]):
            dpg.delete_item(self._main_windows[wid])
        self._main_windows.pop(wid, None)

        if wid in self._z_order:
            self._z_order.remove(wid)

        if self._focused_widget == wid:
            self._focused_widget = None

        self._needs_redraw = True

    # ------------------------------------------------------------------
    # GEOMETRY
    # ------------------------------------------------------------------
    def setWidgetGeometry(self, wid: XPWidgetID, x: int, y: int, w: int, h: int) -> None:
        """Set the geometry of an XPWidget in global screen coordinates."""
        if wid in self._widgets:
            self._widgets[wid]["geometry"] = (x, y, w, h)
            if self._classes.get(wid) == XPPython3.xp.WidgetClass_MainWindow:
                self._main_geometry_applied = False
            else:
                self._container_geom_applied.pop(wid, None)
            self._needs_redraw = True

    def getWidgetGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        """Return the geometry of an XPWidget as (left, top, right, bottom)."""
        x, y, w, h = self._widgets.get(wid, {}).get("geometry", (0, 0, 0, 0))
        return x, y, x + w, y - h

    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        """Return the exposed geometry of an XPWidget."""
        return self.getWidgetGeometry(wid)

    # ------------------------------------------------------------------
    # PROPERTIES
    # ------------------------------------------------------------------
    def setWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID, value: Any) -> None:
        """
        Set an XPWidget property value using real X‑Plane semantics.

        This method updates the internal property store, marks the widget tree
        for redraw, synchronizes the DearPyGui representation, and delegates
        scrollbar slider-position updates to a real‑SDK‑accurate handler.

        Real X‑Plane scrollbars do not send the absolute slider position in p2
        when Msg_ScrollBarSliderPositionChanged fires. Instead:

            p1 = the scrollbar widget ID
            p2 = the delta (change amount), often zero during drag events

        The actual slider position is stored only in the widget property
        Property_ScrollBarSliderPosition and must be read from there by plugins.
        """
        if wid not in self._widgets:
            return None

        # Update internal property
        self._widgets[wid]["properties"][prop] = value
        self._needs_redraw = True

        wclass = self._classes.get(wid)
        dpg_id = self._dpg_ids.get(wid)

        # ------------------------------------------------------------------
        # ScrollBar (delegate slider-position updates)
        # ------------------------------------------------------------------
        if wclass == self.xp.WidgetClass_ScrollBar:

            # Min/max updates stay inline
            if prop == self.xp.Property_ScrollBarMin and dpg_id and dpg.is_item_ok(dpg_id):
                dpg.configure_item(dpg_id, min_value=int(value))

            if prop == self.xp.Property_ScrollBarMax and dpg_id and dpg.is_item_ok(dpg_id):
                dpg.configure_item(dpg_id, max_value=int(value))

            # Delegate slider-position updates to real‑SDK‑accurate handler
            if prop == self.xp.Property_ScrollBarSliderPosition:
                return self._fakexp_scrollbar_set_position(wid, value)

    def getWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID) -> Any:
        """Retrieve an XPWidget property value."""
        return self._widgets.get(wid, {}).get("properties", {}).get(prop)

    # ------------------------------------------------------------------
    # VISIBILITY
    # ------------------------------------------------------------------
    def showWidget(self, wid: XPWidgetID) -> None:
        """Make an XPWidget visible."""
        if wid in self._widgets:
            self._widgets[wid]["visible"] = True
            self._needs_redraw = True

    def hideWidget(self, wid: XPWidgetID) -> None:
        """Hide an XPWidget."""
        if wid in self._widgets:
            self._widgets[wid]["visible"] = False
            self._needs_redraw = True

    def isWidgetVisible(self, wid: XPWidgetID) -> bool:
        """Return True if the widget is visible."""
        return bool(self._widgets.get(wid, {}).get("visible", False))

    # ------------------------------------------------------------------
    # CALLBACKS + MESSAGE DISPATCH
    # ------------------------------------------------------------------
    def addWidgetCallback(self, wid: XPWidgetID, callback: XPWidgetCallback) -> None:
        """Register a callback for an XPWidget."""
        self._callbacks.setdefault(wid, []).append(callback)

    def sendMessageToWidget(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage,
        param1: Any,
        param2: Any,
    ) -> None:
        """
        Send a message to an XPWidget and bubble it up the parent chain.

        OPTION B (prod-matching) semantics:
            - The callback 'widget' argument is the CURRENT widget receiving the message
              (i.e., the bubbling target), not the origin.
            - The origin is conveyed via param1/param2 per SDK message contract.

        Notes:
            - Parent relationships are stored verbatim; no inferred hierarchy.
            - A visited set prevents accidental cycles from causing infinite loops.
            - Message dispatch invalidates rendering to ensure GUI reflects changes.
        """
        current = wid
        visited: set[XPWidgetID] = set()

        while current and current not in visited:
            visited.add(current)
            for cb in self._callbacks.get(current, []):
                cb(msg, int(current), param1, param2)
            current = self._parent.get(current, XPWidgetID(0))

        self._needs_redraw = True

    # ------------------------------------------------------------------
    # HIERARCHY / HIT TESTING
    # ------------------------------------------------------------------
    def getParentWidget(self, wid: XPWidgetID) -> XPWidgetID:
        """Return the parent widget ID or XPWidgetID(0) if root."""
        return self._parent.get(wid, XPWidgetID(0))

    def getWidgetForLocation(self, x: int, y: int) -> Optional[XPWidgetID]:
        """
        Return the frontmost visible widget at the given screen‑space location.

        XPWidgets hit-testing operates in global screen coordinates and returns
        the frontmost widget under the point. FakeXP implements this by scanning
        Z-order from front to back and checking the stored global geometry.
        """
        for wid in reversed(self._z_order):
            w = self._widgets.get(wid)
            if not w or not w["visible"]:
                continue
            gx, gy, gw, gh = w["geometry"]
            if gx <= x <= gx + gw and gy <= y <= gy + gh:
                return wid
        return None

    # ------------------------------------------------------------------
    # Z‑ORDER
    # ------------------------------------------------------------------
    def isWidgetInFront(self, wid: XPWidgetID) -> bool:
        """Return True if the widget is frontmost."""
        return bool(self._z_order) and self._z_order[-1] == wid

    def bringWidgetToFront(self, wid: XPWidgetID) -> None:
        """Move a widget to the front of the Z‑order."""
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.append(wid)
            self._needs_redraw = True

    def pushWidgetBehind(self, wid: XPWidgetID) -> None:
        """Move a widget to the back of the Z‑order."""
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)
            self._needs_redraw = True

    # ------------------------------------------------------------------
    # KEYBOARD FOCUS
    # ------------------------------------------------------------------
    def setKeyboardFocus(self, wid: XPWidgetID) -> None:
        """Set keyboard focus to the given widget (FakeXP stores focus only)."""
        self._focused_widget = wid
        self._needs_redraw = True

    def loseKeyboardFocus(self, wid: XPWidgetID) -> None:
        """Remove keyboard focus if the given widget currently holds it."""
        if self._focused_widget == wid:
            self._focused_widget = None
            self._needs_redraw = True

    # ------------------------------------------------------------------
    # DESCRIPTOR / CLASS
    # ------------------------------------------------------------------
    def setWidgetDescriptor(self, wid: XPWidgetID, text: str) -> None:
        """
        Set the widget descriptor string.

        For text-based widgets, this updates both internal XP state and the
        underlying DearPyGui item so the change is visible immediately.
        """
        self._descriptor[wid] = text

        dpg_id = self._dpg_ids.get(wid)
        if dpg_id is None or not dpg.is_item_ok(dpg_id):
            return

        wclass = self._classes.get(wid)

        if wclass == XPPython3.xp.WidgetClass_TextField:
            dpg.set_value(dpg_id, text.strip())
        elif wclass == XPPython3.xp.WidgetClass_Caption:
            dpg.configure_item(dpg_id, default_value=text)
        elif wclass == XPPython3.xp.WidgetClass_Button:
            dpg.configure_item(dpg_id, label=text)
        elif wclass == XPPython3.xp.WidgetClass_ScrollBar:
            pass
        else:
            dpg.configure_item(dpg_id, default_value=text)

        self._needs_redraw = True

    def getWidgetDescriptor(self, wid: XPWidgetID) -> str:
        """Return the widget descriptor string."""
        return self._descriptor.get(wid, "")

    def getWidgetClass(self, wid: XPWidgetID) -> XPWidgetClass:
        """Return the widget class."""
        return self._classes.get(wid, XPPython3.xp.WidgetClass_GeneralGraphics)

    def getWidgetUnderlyingWindow(self, wid: XPWidgetID) -> int:
        """Return the underlying window handle (always 0 in FakeXP)."""
        return 0

    # ------------------------------------------------------------------
    # RENDERING
    # ------------------------------------------------------------------
    def _resolve_dpg_parent(self, wid: XPWidgetID) -> int:
        """
        Resolve the DearPyGui parent item for an XP widget.
        """
        parent = self._parent.get(wid, XPWidgetID(0))

        if self._classes.get(wid) == XPPython3.xp.WidgetClass_MainWindow:
            return 0

        if parent == XPWidgetID(0):
            if self._default_main_window is None:
                self._default_main_window = dpg.add_window(
                    label="FakeXP Default Window",
                    no_scrollbar=True,
                    no_collapse=True,
                )
            return self._default_main_window

        if parent not in self._dpg_ids:
            self._ensure_dpg_item_for_widget(parent)

        return self._dpg_ids[parent]

    def _compute_local_pos(self, wid: XPWidgetID) -> Tuple[int, int]:
        """
        Compute parent-local DearPyGui coordinates from XPWidgets geometry.
        """
        parent = self._parent.get(wid, XPWidgetID(0))
        cx, ctop, _, _ = self._widgets[wid]["geometry"]

        if parent == XPWidgetID(0):
            XPPython3.xp.log(
                f"[FakeXPWidget] local_pos wid={wid} ROOT -> ({cx},{ctop})"
            )
            return cx, ctop

        px, ptop, _, _ = self._widgets[parent]["geometry"]

        x_local = cx - px
        y_local = ptop - ctop

        return x_local, y_local

    def _ensure_dpg_item_for_widget(self, wid: XPWidgetID) -> None:
        """
        Ensure that a DearPyGui representation exists for the given XP widget.
        """
        if wid in self._dpg_ids and dpg.is_item_ok(self._dpg_ids[wid]):
            return

        xp = self.xp
        wclass = self._classes[wid]
        desc = self._descriptor[wid]
        parent_dpg = self._resolve_dpg_parent(wid)

        # ----------------------------------------------------------------------
        # MAIN WINDOW
        # ----------------------------------------------------------------------
        if wclass == xp.WidgetClass_MainWindow:
            if wid in self._main_windows and dpg.is_item_ok(self._main_windows[wid]):
                self._dpg_ids[wid] = self._main_windows[wid]
                return

            dpg_id = dpg.add_window(
                label=desc or "Window",
                no_scrollbar=True,
                no_collapse=True,
            )
            self._main_windows[wid] = dpg_id
            self._dpg_ids[wid] = dpg_id
            return

        # ----------------------------------------------------------------------
        # CHILD CONTAINER
        # ----------------------------------------------------------------------
        cont = self._containers.get(wid)
        if cont is None or not dpg.is_item_ok(cont):
            cont = dpg.add_child_window(
                parent=parent_dpg,
                border=False,
                no_scrollbar=True,
                autosize_x=False,
                autosize_y=False,
            )
            self._containers[wid] = cont
            self._container_geom_applied.pop(wid, None)

        # ----------------------------------------------------------------------
        # WIDGET TYPES
        # ----------------------------------------------------------------------
        if wclass == xp.WidgetClass_Caption:
            dpg_id = dpg.add_text(default_value=(desc or "").strip(), parent=cont)

        elif wclass == xp.WidgetClass_TextField:
            def _on_text(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                self._edit_buffer[widget_id] = app_data
                # XP semantics: param1 identifies the text field; param2 carries the new text.
                self.sendMessageToWidget(
                    widget_id,
                    xp.Msg_TextFieldChanged,
                    widget_id,
                    app_data,
                )

            dpg_id = dpg.add_input_text(
                default_value=(desc or "").strip(),
                parent=cont,
                callback=_on_text,
                user_data=wid,
                no_spaces=True,
            )

        elif wclass == xp.WidgetClass_ScrollBar:
            min_v = int(self.getWidgetProperty(wid, xp.Property_ScrollBarMin) or 0)
            max_v = int(self.getWidgetProperty(wid, xp.Property_ScrollBarMax) or 100)
            cur_v = int(self.getWidgetProperty(wid, xp.Property_ScrollBarSliderPosition) or min_v)

            def _on_scroll(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                new_pos = int(app_data)
                self.setWidgetProperty(widget_id, xp.Property_ScrollBarSliderPosition, new_pos)
                # XP semantics: param1 identifies the scrollbar; param2 carries the new position.
                self.sendMessageToWidget(
                    widget_id,
                    xp.Msg_ScrollBarSliderPositionChanged,
                    widget_id,
                    new_pos,
                )

            dpg_id = dpg.add_slider_int(
                label=desc or "Slider",
                parent=cont,
                min_value=min_v,
                max_value=max_v,
                default_value=cur_v,
                callback=_on_scroll,
                user_data=wid,
            )

        elif wclass == xp.WidgetClass_Button:
            def _on_button(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                # XP semantics: param1 identifies the pressed button.
                self.sendMessageToWidget(
                    widget_id,
                    xp.Msg_PushButtonPressed,
                    widget_id,
                    None,
                )

            dpg_id = dpg.add_button(
                label=desc or "",
                parent=cont,
                callback=_on_button,
                user_data=wid,
            )

        else:
            dpg_id = dpg.add_text(desc or f"Widget {wid}", parent=cont)

        self._dpg_ids[wid] = dpg_id

    def _render_widgets(self) -> None:
        """
        Apply XPWidgets geometry to DearPyGui items once layout is valid.
        """
        if not self._layout_ready:
            return

        for wid in list(self._widgets.keys()):
            self._ensure_dpg_item_for_widget(wid)

            dpg_id = self._dpg_ids.get(wid)
            if dpg_id is None or not dpg.is_item_ok(dpg_id):
                continue

            x, top, w, h = self._widgets[wid]["geometry"]
            wclass = self._classes.get(wid)

            if wclass == self.xp.WidgetClass_MainWindow:
                if not self._main_geometry_applied:
                    dpg.configure_item(dpg_id, pos=(x, top), width=w, height=h)
                continue

            cont = self._containers.get(wid)
            if cont is None or not dpg.is_item_ok(cont):
                continue

            lx, ly = self._compute_local_pos(wid)
            key = (lx, ly, w, h)

            if self._container_geom_applied.get(wid) != key:
                dpg.configure_item(cont, pos=(lx, ly), width=w, height=h)
                self._container_geom_applied[wid] = key

        self._main_geometry_applied = True

    def _dispatch_draw(self, wid: XPWidgetID) -> None:
        """
        Dispatch Msg_Draw callbacks for a widget subtree.
        """
        if not self.isWidgetVisible(wid):
            return

        for cb in self._callbacks.get(wid, []):
            cb(self.xp.Msg_Draw, wid, None, None)

        for child, parent in self._parent.items():
            if parent == wid:
                self._dispatch_draw(child)

    def _draw_all_widgets(self) -> None:
        """
        Render (if needed) and dispatch draw callbacks for all widget trees.
        """
        if not self._needs_redraw:
            return

        self._render_widgets()

        for wid in list(self._widgets.keys()):
            if self._parent.get(wid, XPWidgetID(0)) == XPWidgetID(0):
                self._dispatch_draw(wid)

        self._needs_redraw = False

    def _fakexp_scrollbar_set_position(self, wid, new_pos):
        """
        Update a scrollbar's slider position using real X‑Plane semantics.

        Real X‑Plane does NOT send the absolute slider position in p2 when
        Msg_ScrollBarSliderPositionChanged is dispatched. Instead:

            p1 = the scrollbar widget ID
            p2 = the delta (change amount), which is often zero during drag events

        The actual slider position is stored only in the widget property
        Property_ScrollBarSliderPosition and must be read from there by plugins.

        This function updates the internal property, computes the delta relative
        to the previous position, synchronizes the DearPyGui slider without
        triggering callbacks, and dispatches a real‑SDK‑accurate message.
        """
        # Retrieve previous slider position
        old_pos = int(
            self._widgets[wid]["properties"].get(
                self.xp.Property_ScrollBarSliderPosition, 0
            )
        )

        new_pos = int(new_pos)
        delta = new_pos - old_pos

        # Update internal property
        self._widgets[wid]["properties"][self.xp.Property_ScrollBarSliderPosition] = new_pos

        # Sync DPG slider without triggering callbacks
        dpg_id = self._dpg_ids.get(wid)
        if dpg_id and dpg.is_item_ok(dpg_id):
            dpg.configure_item(dpg_id, default_value=new_pos)

        # Dispatch real‑SDK‑accurate message
        self.sendMessageToWidget(
            wid,
            self.xp.Msg_ScrollBarSliderPositionChanged,
            wid,  # p1 = widget ID
            delta,  # p2 = delta (NOT absolute value)
        )
