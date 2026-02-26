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
#   - Must match XPPython3 xp widget API names and signatures exactly.
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
        return (x, y, x + w, y - h)

    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        """Return the exposed geometry of an XPWidget."""
        return self.getWidgetGeometry(wid)

    # ------------------------------------------------------------------
    # PROPERTIES
    # ------------------------------------------------------------------
    def setWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID, value: Any) -> None:
        """Set an XPWidget property value."""
        if wid in self._widgets:
            self._widgets[wid]["properties"][prop] = value
            self._needs_redraw = True

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

        XPWidgets message delivery is hierarchical: a message is delivered to the
        target widget, then (optionally) to its parent, and so on until the root.
        FakeXP mirrors this by walking the stored parent chain.

        Notes:
            - Parent relationships are stored verbatim; no inferred hierarchy.
            - A visited set prevents accidental cycles from causing infinite loops.
            - Message dispatch invalidates rendering to ensure GUI reflects changes.

        Args:
            wid: Target widget ID.
            msg: XPWidgets message ID.
            param1: Message parameter 1 (SDK-shaped, passed through).
            param2: Message parameter 2 (SDK-shaped, passed through).
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

        Args:
            x: Screen-space X coordinate.
            y: Screen-space Y coordinate.

        Returns:
            The frontmost XPWidgetID under (x, y), or None if no widget matches.
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
        if dpg_id is not None and dpg.is_item_ok(dpg_id):
            if self._classes.get(wid) == XPPython3.xp.WidgetClass_TextField:
                dpg.set_value(dpg_id, text.strip())
            else:
                dpg.set_value(dpg_id, text)

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

        XPWidgets use integer widget IDs and a parent ID of 0 to indicate
        root-level widgets. DearPyGui requires an explicit parent item.

        Resolution rules:
            - MainWindow widgets have no parent (return 0).
            - Root widgets (parent == 0) are attached to a default main window.
            - Child widgets are attached to their parent's DearPyGui item.

        The default main window is created lazily and reused.

        Args:
            wid: XPWidgetID whose parent is being resolved.

        Returns:
            DearPyGui item ID to use as the parent.
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

        XPWidgets geometry is expressed in global, screen-space coordinates
        for all widgets, including children. DearPyGui positions items relative
        to their immediate parent container.

        This method converts XPWidgets global geometry into parent-local
        coordinates suitable for DearPyGui by applying the transform:

            x_local = child_left - parent_left
            y_local = parent_top - child_top

        Notes:
            - XPWidgets Y coordinates grow upward; DearPyGui Y grows downward.
            - DearPyGui child_window positioning is already relative to the
              content region, so no title-bar compensation is required.
            - This transform must be applied during render, not creation.

        Args:
            wid: XPWidgetID of the widget being positioned.

        Returns:
            (x, y) position relative to the parent container.
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

        This method performs structural creation only and never applies geometry.
        Geometry is handled separately during render once layout is valid.

        Design notes:
            - DearPyGui does not support absolute positioning of normal widgets.
            - Each XP widget is wrapped in its own child_window container.
            - child_window autosizing is disabled so explicit geometry is respected.
            - MainWindow widgets are created exactly once and cached.

        This method is idempotent and safe to call repeatedly.

        Args:
            wid: XPWidgetID to ensure a DearPyGui item exists for.
        """

        if wid in self._dpg_ids and dpg.is_item_ok(self._dpg_ids[wid]):
            return

        wclass = self._classes[wid]
        desc = self._descriptor[wid]
        parent_dpg = self._resolve_dpg_parent(wid)

        if wclass == self.xp.WidgetClass_MainWindow:
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

        if wclass == self.xp.WidgetClass_Caption:
            dpg_id = dpg.add_text(default_value=(desc or "").strip(), parent=cont)
        elif wclass == self.xp.WidgetClass_TextField:
            def _on_text(sender, app_data, user_data):
                self._edit_buffer[XPWidgetID(user_data)] = app_data
                self.sendMessageToWidget(
                    XPWidgetID(user_data),
                    self.xp.Msg_TextFieldChanged,
                    app_data,
                    None,
                )

            dpg_id = dpg.add_input_text(
                default_value=(desc or "").strip(),
                parent=cont,
                callback=_on_text,
                user_data=wid,
                no_spaces=True,
            )
        elif wclass == self.xp.WidgetClass_ScrollBar:
            dpg_id = dpg.add_slider_int(label=desc or "Slider", parent=cont)
        elif wclass == self.xp.WidgetClass_Button:

            def _on_button(sender, app_data, user_data):
                self.sendMessageToWidget(
                    XPWidgetID(user_data),
                    self.xp.Msg_PushButtonPressed,
                    None,
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

        Responsibilities:
            - Create any missing DearPyGui items.
            - Apply MainWindow geometry exactly once after the first frame.
            - Apply child widget geometry via their container windows.
            - Convert XPWidgets global geometry into parent-local coordinates.

        Critical invariants:
            - Geometry must NOT be applied before DearPyGui's first frame.
            - MainWindow geometry must NOT be re-applied every frame, or user
              window moves will snap back.
            - Child widget geometry is re-applied only when XP explicitly changes it.

        This method is called from the graphics loop and is intentionally
        side-effect free beyond geometry application.
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

        XPWidgets draw is callback-driven. FakeXP mirrors this by invoking
        registered callbacks with Msg_Draw and then recursing into children
        based on the stored parent map.
        """
        # Skip invisible widgets entirely
        # if not self._visible.get(wid, True):
        #    return

        # Dispatch Msg_Draw to this widget
        for cb in self._callbacks.get(wid, []):
            cb(self.xp.Msg_Draw, wid, None, None)

        # Recurse into children (depth-first)
        for child, parent in self._parent.items():
            if parent == wid:
                self._dispatch_draw(child)

    def _draw_all_widgets(self) -> None:
        """
        Render (if needed) and dispatch draw callbacks for all widget trees.

        XPWidgets are event-driven rather than continuously redrawn. FakeXP
        tracks invalidation via _needs_redraw and only performs work when
        something changed (geometry, visibility, descriptor, messages, etc.).

        Flow:
            1) Apply geometry (deferred until layout is valid).
            2) Dispatch Msg_Draw starting from root widgets (parent == 0).
            3) Clear invalidation flag.
        """
        if not self._needs_redraw:
            return

        self._render_widgets()

        for wid in list(self._widgets.keys()):
            if self._parent.get(wid, XPWidgetID(0)) == XPWidgetID(0):
                self._dispatch_draw(wid)

        self._needs_redraw = False
