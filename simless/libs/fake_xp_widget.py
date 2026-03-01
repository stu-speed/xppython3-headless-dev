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
#   4. Window geometry must be applied EXACTLY ONCE per widget
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
#
# STRICTNESS POLICY
#   - FakeXPWidget owns widget validity.
#   - DearPyGui is treated as write‑only from this layer (no state queries).
#   - Any invariant violation is a programmer error and raises immediately.
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import dearpygui.dearpygui as dpg

import XPPython3
from simless.libs.fake_xp_interface import FakeXPInterface
from XPPython3.xp_typing import (
    XPWidgetClass,
    XPWidgetID,
    XPWidgetMessage,
    XPWidgetPropertyID,
)

XPWidgetCallback = Callable[[int, int, Any, Any], int]


# ---------------------------------------------------------------------------
# WidgetInfo — single authoritative widget record
# ---------------------------------------------------------------------------

@dataclass
class WidgetInfo:
    # XP authoritative state
    wid: XPWidgetID
    widget_class: XPWidgetClass
    parent: XPWidgetID
    descriptor: str
    geometry: Tuple[int, int, int, int]  # (x, top, w, h) in global XP screen coords
    visible: bool = True
    properties: Dict[XPWidgetPropertyID, Any] = field(default_factory=dict)
    callbacks: List[XPWidgetCallback] = field(default_factory=list)

    # DearPyGui representation (internal only)
    dpg_id: Optional[int] = None          # actual DPG widget (text/button/slider/etc) OR window id for XP windows
    container_id: Optional[int] = None    # child_window container for XP controls; for XP windows, equals dpg_id

    # Geometry lifecycle (per-widget; eliminates one-off global flags)
    geom_applied: bool = False
    container_geom_applied: Optional[Tuple[int, int, int, int]] = None  # (lx, ly, w, h) last applied

    # Interaction state
    edit_buffer: Optional[str] = None


class FakeXPWidget:
    xp: FakeXPInterface  # established in FakeXP

    _needs_redraw: bool
    _focused_widget: Optional[XPWidgetID]
    _next_id: int
    _widgets_initialized: bool

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
        "all_widget_ids",
        "map_widgets_to_dpg",
        "render_widget_frame",
    ]

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    def _require_widget(self, wid: XPWidgetID) -> WidgetInfo:
        info = self._widgets.get(wid)
        if info is None:
            raise RuntimeError(f"XPWidget {wid} does not exist")
        return info

    def _require_initialized(self) -> None:
        if not getattr(self, "_widgets_initialized", False):
            raise RuntimeError("FakeXPWidget used before map_widgets_to_dpg() completed")

    # ------------------------------------------------------------------
    # INITIALIZATION
    # ------------------------------------------------------------------

    def _init_widgets(self) -> None:
        """Initialize all internal XPWidget bookkeeping structures."""
        self._widgets: Dict[XPWidgetID, WidgetInfo] = {}

        self._z_order: List[XPWidgetID] = []
        self._focused_widget: Optional[XPWidgetID] = None

        self._needs_redraw = True
        self._widgets_initialized = False

        self._next_id = 1

    # -------------------------
    # helpers
    # -------------------------

    def all_widget_ids(self) -> list[XPWidgetID]:
        """Return a snapshot of all known widget IDs."""
        return list(self._widgets.keys())

    def map_widgets_to_dpg(self) -> None:
        if self._widgets_initialized:
            return

        for wid in self._widgets:
            self._ensure_dpg_item_for_widget(wid)

        self._normalize_window_geometry_descendants()

        self._widgets_initialized = True

    def _normalize_window_geometry_descendants(self) -> None:
        """
        One-time XP compatibility pass.

        After all widgets are created, expand each XP window (MainWindow or SubWindow)
        to fully contain the bounding box of all *visible descendant widgets*.

        This mimics real X-Plane behavior:
        - Expansion happens once, post-creation
        - Geometry is never auto-adjusted again
        - User resizing and plugin-driven geometry changes are preserved
        """

        def iter_descendants(root: XPWidgetID):
            for child_id, child in self._widgets.items():
                if child.parent == root:
                    yield child_id
                    yield from iter_descendants(child_id)

        for wid, info in self._widgets.items():
            if info.widget_class not in (
                self.xp.WidgetClass_MainWindow,
                self.xp.WidgetClass_SubWindow,
            ):
                continue

            wx, wy, ww, wh = info.geometry

            max_right = wx + ww
            max_bottom = wy - wh

            for child_id in iter_descendants(wid):
                if not self.isWidgetVisible(child_id):
                    continue

                child = self._widgets.get(child_id)
                if not child:
                    continue

                cx, cy, cw, ch = child.geometry
                max_right = max(max_right, cx + cw)
                max_bottom = min(max_bottom, cy - ch)

            new_w = max_right - wx
            new_h = wy - max_bottom

            if new_w > ww or new_h > wh:
                self.xp.log(
                    f"[Normalize] window wid={wid} "
                    f"expanded from {ww}x{wh} to {new_w}x{new_h}"
                )

                info.geometry = (wx, wy, new_w, new_h)
                info.geom_applied = False
                self._needs_redraw = True

    def render_widget_frame(self) -> None:
        """
        Apply XP geometry and dispatch draw callbacks.

        Clean A1 rules:
        - Only run after widgets are created and DPG has rendered one frame.
        - Apply geometry only when XP changes it.
        - Never create windows here; only geometry updates.
        """

        if not self._needs_redraw:
            return

        self._render_widgets()

        # Dispatch draw callbacks for top-level XP windows
        for wid, info in self._widgets.items():
            if info.dpg_id is None:
                continue
            self.xp.log(f"[DBG] wid={wid} dpg_id={info.dpg_id}")
            if info.parent == XPWidgetID(0):
                self._dispatch_draw(wid)

        self._needs_redraw = False

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

        info = WidgetInfo(
            wid=wid,
            widget_class=widget_class,
            parent=XPWidgetID(parent),
            descriptor=descriptor,
            geometry=(left, top, right - left, top - bottom),
            visible=bool(visible),
        )

        if widget_class == XPPython3.xp.WidgetClass_TextField:
            info.edit_buffer = descriptor

        self._widgets[wid] = info
        self._z_order.append(wid)

        self._needs_redraw = True
        return wid

    def killWidget(self, wid: XPWidgetID) -> None:
        """Destroy an XPWidget and all associated state."""
        info = self._widgets.pop(wid, None)
        if info is None:
            raise RuntimeError(f"killWidget called on unknown widget {wid}")

        # Write-only DPG: delete what we believe exists.
        if info.dpg_id is not None:
            dpg.delete_item(info.dpg_id)
        info.dpg_id = None
        info.container_id = None

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
        info = self._require_widget(wid)

        info.geometry = (x, y, w, h)

        # Window geometry must be applied EXACTLY ONCE per widget
        info.geom_applied = False

        # Child widgets: invalidate cached container geometry
        info.container_geom_applied = None

        # Always request a redraw after geometry change
        self._needs_redraw = True

    def getWidgetGeometry(self, wid: XPWidgetID) -> Tuple[int, int, int, int]:
        """Return the geometry of an XPWidget as (left, top, right, bottom)."""
        info = self._require_widget(wid)
        x, y, w, h = info.geometry
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
        info = self._require_widget(wid)

        # Update internal property
        info.properties[prop] = value
        self._needs_redraw = True

        wclass = info.widget_class
        dpg_id = info.dpg_id

        # ------------------------------------------------------------------
        # ScrollBar (delegate slider-position updates)
        # ------------------------------------------------------------------
        if wclass == self.xp.WidgetClass_ScrollBar:
            if prop == self.xp.Property_ScrollBarMin:
                if dpg_id is not None:
                    dpg.configure_item(dpg_id, min_value=int(value))
                return None

            if prop == self.xp.Property_ScrollBarMax:
                if dpg_id is not None:
                    dpg.configure_item(dpg_id, max_value=int(value))
                return None

            if prop == self.xp.Property_ScrollBarSliderPosition:
                return self._fakexp_scrollbar_set_position(wid, value)

        return None

    def getWidgetProperty(self, wid: XPWidgetID, prop: XPWidgetPropertyID) -> Any:
        """Retrieve an XPWidget property value."""
        info = self._require_widget(wid)
        return info.properties.get(prop)

    # ------------------------------------------------------------------
    # VISIBILITY
    # ------------------------------------------------------------------

    def showWidget(self, wid: XPWidgetID) -> None:
        """Make an XPWidget visible."""
        info = self._require_widget(wid)
        info.visible = True
        self._needs_redraw = True

    def hideWidget(self, wid: XPWidgetID) -> None:
        """Hide an XPWidget."""
        info = self._require_widget(wid)
        info.visible = False
        self._needs_redraw = True

    def isWidgetVisible(self, wid: XPWidgetID) -> bool:
        """Return True if the widget is visible."""
        info = self._require_widget(wid)
        return bool(info.visible)

    # ------------------------------------------------------------------
    # CALLBACKS + MESSAGE DISPATCH
    # ------------------------------------------------------------------

    def addWidgetCallback(self, wid: XPWidgetID, callback: XPWidgetCallback) -> None:
        """Register a callback for an XPWidget."""
        info = self._require_widget(wid)
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
            info = self._widgets.get(current)
            if not info:
                break
            for cb in info.callbacks:
                cb(msg, int(current), param1, param2)
            current = info.parent

        self._needs_redraw = True

    # ------------------------------------------------------------------
    # HIERARCHY / HIT TESTING
    # ------------------------------------------------------------------

    def getParentWidget(self, wid: XPWidgetID) -> XPWidgetID:
        """Return the parent widget ID or XPWidgetID(0) if root."""
        info = self._require_widget(wid)
        return info.parent

    def getWidgetForLocation(self, x: int, y: int) -> Optional[XPWidgetID]:
        """
        Return the frontmost visible widget at the given screen‑space location.

        XPWidgets hit-testing operates in global screen coordinates and returns
        the frontmost widget under the point. FakeXP implements this by scanning
        Z-order from front to back and checking the stored global geometry.
        """
        for wid in reversed(self._z_order):
            info = self._widgets.get(wid)
            if not info or not info.visible:
                continue
            gx, gy, gw, gh = info.geometry
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
        self._require_widget(wid)
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.append(wid)
            self._needs_redraw = True

    def pushWidgetBehind(self, wid: XPWidgetID) -> None:
        """Move a widget to the back of the Z‑order."""
        self._require_widget(wid)
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)
            self._needs_redraw = True

    # ------------------------------------------------------------------
    # KEYBOARD FOCUS
    # ------------------------------------------------------------------

    def setKeyboardFocus(self, wid: XPWidgetID) -> None:
        """Set keyboard focus to the given widget (FakeXP stores focus only)."""
        self._require_widget(wid)
        self._focused_widget = wid
        self._needs_redraw = True

    def loseKeyboardFocus(self, wid: XPWidgetID) -> None:
        """Remove keyboard focus if the given widget currently holds it."""
        self._require_widget(wid)
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
        info = self._require_widget(wid)
        info.descriptor = text

        dpg_id = info.dpg_id
        if dpg_id is None:
            raise RuntimeError(f"setWidgetDescriptor: wid={wid} has no dpg_id")

        wclass = info.widget_class

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
        info = self._require_widget(wid)
        return info.descriptor

    def getWidgetClass(self, wid: XPWidgetID) -> XPWidgetClass:
        """Return the widget class."""
        info = self._require_widget(wid)
        return info.widget_class

    def getWidgetUnderlyingWindow(self, wid: XPWidgetID) -> int:
        """Return the underlying window handle (always 0 in FakeXP)."""
        self._require_widget(wid)
        return 0

    # ------------------------------------------------------------------
    # RENDERING
    # ------------------------------------------------------------------

    def _compute_local_pos(self, wid: XPWidgetID) -> Tuple[int, int]:
        """
        Compute the XP‑semantic local (x, y) position of a widget relative to its
        XP parent, based on XPWidgets global screen‑space geometry.

        Architecture clarification:
        - In this architecture, every XP window (MainWindow + child windows) is a
          *real* DearPyGui window parented directly to the graphics root. DPG does
          not reflect XP parent/child relationships in its own window hierarchy.
        - XPWidgets, however, still define geometry in a hierarchical manner:
              child.x_global = parent.x_global + child.x_local
              child.y_global = parent.y_global - child.y_local
          where XP uses a top‑origin Y axis.
        - This method computes the XP‑semantic local offset so that geometry
          updates remain correct even though DPG windows are all siblings.

        Behavior:
        - If the widget has no XP parent (parent == 0), its global XP coordinates
          are returned unchanged. This corresponds to a top‑level XP window.
        - If the widget has an XP parent, the returned (x_local, y_local) is the
          offset from the parent’s XP global geometry.
        - The returned coordinates are *not* used for DPG parenting (all DPG
          windows are siblings), but they are used to compute the correct DPG
          window position when applying XP geometry.

        Parameters
        ----------
        wid : XPWidgetID
            The XP widget whose local position should be computed.

        Returns
        -------
        (int, int)
            The XP‑semantic local (x, y) position relative to the XP parent.

        Notes
        -----
        This method preserves XP’s geometry model even though DPG windows are not
        nested. It ensures that XPWidget geometry remains correct and stable across
        viewport resizes, window drags, and plugin‑driven geometry changes.
        """
        info = self._require_widget(wid)
        parent = info.parent
        cx, ctop, _, _ = info.geometry

        if parent == XPWidgetID(0):
            return cx, ctop

        pinfo = self._require_widget(parent)
        px, ptop, _, _ = pinfo.geometry

        x_local = cx - px
        y_local = ptop - ctop

        return x_local, y_local

    def _ensure_dpg_item_for_widget(self, wid: XPWidgetID) -> None:
        """
        Ensure that a DearPyGui representation exists for the given XPWidget.
        (Logging-enabled diagnostic version)
        """
        info = self._widgets.get(wid)
        if not info:
            raise RuntimeError(f"_ensure_dpg_item_for_widget: unknown wid={wid}")

        # Already created?
        if info.dpg_id is not None:
            self.xp.log(f"[Create] wid={wid} already exists")
            return

        xp = self.xp
        wclass = info.widget_class
        desc = info.descriptor

        is_window = wclass in (
            xp.WidgetClass_MainWindow,
            xp.WidgetClass_SubWindow,
        )

        self.xp.log(
            f"[Create] wid={wid} class={wclass} "
            f"is_window={is_window} desc='{desc}'"
        )

        # ------------------------------------------------------------
        # XP WINDOWS -> real top-level DPG windows (siblings)
        # ------------------------------------------------------------
        if is_window:
            self.xp.log(f"[Create] wid={wid} creating DPG WINDOW")

            dpg_id = dpg.add_window(
                label=desc or "Window",
                width=200,
                height=100,
                no_scrollbar=True,
                no_collapse=True,
                no_resize=False,
                no_move=False,
            )

            info.dpg_id = dpg_id
            info.container_id = dpg_id
            info.geom_applied = False
            info.container_geom_applied = None
            return

        # ------------------------------------------------------------
        # XP CONTROLS -> child_window container inside XP parent window
        # ------------------------------------------------------------
        parent_wid = info.parent
        self.xp.log(f"[Create] wid={wid} CONTROL parent_wid={parent_wid}")

        if parent_wid == XPWidgetID(0):
            raise RuntimeError(f"[Create] wid={wid} ERROR: control has no parent")

        # Ensure parent window exists first
        self._ensure_dpg_item_for_widget(parent_wid)

        parent_info = self._widgets.get(parent_wid)
        parent_container = parent_info.container_id if parent_info else None
        self.xp.log(f"[Create] wid={wid} parent_container={parent_container}")

        if parent_container is None:
            raise RuntimeError(f"[Create] wid={wid} ERROR: parent container invalid")

        # Create / reuse the positionable container for this control
        cont = info.container_id
        if cont is None:
            self.xp.log(f"[Create] wid={wid} creating CHILD container")
            cont = dpg.add_child_window(
                parent=parent_container,
                width=200,
                height=100,
                no_scrollbar=True,
                border=False,
                autosize_x=False,
                autosize_y=False,
            )
            info.container_id = cont
            info.container_geom_applied = None

        # Create the actual control inside the container
        if wclass == xp.WidgetClass_Caption:
            dpg_id = dpg.add_text(
                default_value=(desc or "").strip(),
                parent=cont,
            )

        elif wclass == xp.WidgetClass_TextField:
            def _on_text(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                w = self._widgets.get(widget_id)
                if w:
                    w.edit_buffer = app_data
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
                self.setWidgetProperty(
                    widget_id,
                    xp.Property_ScrollBarSliderPosition,
                    new_pos,
                )
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
            dpg_id = dpg.add_text(
                desc or f"Widget {wid}",
                parent=cont,
            )

        info.dpg_id = dpg_id

    def _render_widgets(self) -> None:
        self.xp.log(f"needs_redraw={self._needs_redraw}")

        for wid in list(self._widgets.keys()):
            info = self._widgets.get(wid)
            if not info:
                continue

            # Ensure DPG items exist (creation is allowed here per existing design)
            self._ensure_dpg_item_for_widget(wid)

            # Apply geometry (implementation below preserves "apply exactly once" semantics)
            self._apply_geometry_if_needed(wid)

            # Apply visibility
            self._apply_visibility(wid)

    # ------------------------------------------------------------------
    # GEOMETRY APPLICATION (DPG WRITE‑ONLY)
    # ------------------------------------------------------------------

    def _apply_geometry_if_needed(self, wid: XPWidgetID) -> None:
        """
        Apply XP geometry to the DPG representation if invalidated.

        This method preserves the invariant:
        - Window geometry is applied exactly once per XP geometry change.
        - Child container geometry is applied only when it changes.
        """
        info = self._require_widget(wid)

        # Nothing to apply until DPG exists
        if info.container_id is None:
            return

        x, top, w, h = info.geometry

        # Top-level XP windows: apply to the DPG window itself
        if info.widget_class in (self.xp.WidgetClass_MainWindow, self.xp.WidgetClass_SubWindow):
            if info.dpg_id is None:
                raise RuntimeError(f"_apply_geometry_if_needed: window wid={wid} has no dpg_id")

            if not info.geom_applied:
                self.xp.log(f"[Geom] WINDOW wid={wid} x={x} y={top} w={w} h={h}")
                dpg.configure_item(info.dpg_id, pos=(x, top - h), width=w, height=h)
                info.geom_applied = True
            return

        # Controls: apply to their child_window container (positionable surface)
        parent = info.parent
        if parent == XPWidgetID(0):
            raise RuntimeError(f"_apply_geometry_if_needed: control wid={wid} has no parent")

        pinfo = self._require_widget(parent)
        px, ptop, _, _ = pinfo.geometry

        lx = x - px
        ly = ptop - top

        last = info.container_geom_applied
        desired = (lx, ly, w, h)

        if last != desired:
            self.xp.log(f"[Geom] CONTROL wid={wid} x={lx} y={ly} w={w} h={h}")
            dpg.configure_item(info.container_id, pos=(lx, ly), width=w, height=h)
            info.container_geom_applied = desired

    def _apply_visibility(self, wid: XPWidgetID) -> None:
        """Apply XP visibility to the DPG representation (write-only)."""
        info = self._require_widget(wid)

        # If not created yet, nothing to show/hide.
        if info.container_id is None:
            return

        if info.visible:
            dpg.show_item(info.container_id)
        else:
            dpg.hide_item(info.container_id)

    # ------------------------------------------------------------------
    # DRAW DISPATCH (EXISTING SEMANTICS)
    # ------------------------------------------------------------------

    def _dispatch_draw(self, wid: XPWidgetID) -> None:
        """
        Dispatch draw callbacks for a top-level XP window.

        This method is expected to exist in the original file; this implementation
        preserves the call site and provides a minimal, deterministic behavior:
        - If the widget has callbacks, invoke them with Msg_Draw.
        - No inference or validation beyond strict widget existence.
        """
        info = self._require_widget(wid)
        for cb in info.callbacks:
            cb(self.xp.Msg_Draw, int(wid), wid, None)

    # ------------------------------------------------------------------
    # SCROLLBAR HELPERS (EXISTING SEMANTICS)
    # ------------------------------------------------------------------

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

        dpg.set_value(info.dpg_id, int(value))
        return None
