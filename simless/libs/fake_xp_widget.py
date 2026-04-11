# simless/libs/fake_xp/fake_xp_widget.py
# ===========================================================================
# FakeXPWidget — Widget subsystem mixin for FakeXP
#
# ROLE
#   Provide a deterministic, minimal, X‑Plane‑authentic XPWidgets façade for
#   sim‑less execution. This subsystem mirrors the public self xp widget
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
#   - Graphics module must handle all dgp calls.  DO NOT IMPORT DPG
#   - Must match self xp widget API names, signatures, and functionality.
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

from typing import Any, cast, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import WGeom, XPWidgetCallback
from simless.libs.widget import WidgetManager
from XPPython3.xp_typing import XPWidgetClass, XPWidgetID, XPWidgetMessage, XPWidgetPropertyID

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPWidget:
    @property
    def fake_xp(self) -> FakeXP:
        return cast("FakeXP", cast(object, self))

    @property
    def wm(self) -> WidgetManager:
        return self.fake_xp.widget_manager

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

        geom = WGeom(left, top, right, bottom)
        visible_bool = bool(visible)

        # ---------------------------------------------------------
        # ROOT WIDGET
        # ---------------------------------------------------------
        if is_root:
            if parent != 0:
                raise ValueError(f"Root widget must have parent=0 (got parent={parent})")

            # Register the window with authoritative geometry + visibility
            window_info = self.fake_xp.window_manager.register_windowex(
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                visible=visible_bool,
                decoration=self.fake_xp.WindowDecorationRoundRectangle,
                layer=self.fake_xp.WindowLayerFloatingWindows,
            )

            # Use helper
            info = self.wm.create_widget(
                widget_class=widget_class,
                window=window_info,
                geometry=geom,
                parent=None,
                descriptor=descriptor,
                visible=visible_bool,
            )

            # TextField edit buffer
            if widget_class == self.fake_xp.WidgetClass_TextField:
                info.edit_buffer = descriptor

            return info.wid

        # ---------------------------------------------------------
        # NON-ROOT WIDGET
        # ---------------------------------------------------------
        if parent == 0:
            raise ValueError("Non-root widget cannot have parent=0")

        parent_wid = XPWidgetID(parent)
        parent_info = self.wm.require_info(parent_wid)
        window_info = parent_info.window

        # Use helper
        info = self.wm.create_widget(
            widget_class=widget_class,
            window=window_info,
            geometry=geom,
            parent=parent_wid,
            descriptor=descriptor,
            visible=visible_bool,
        )

        # TextField edit buffer
        if widget_class == self.fake_xp.WidgetClass_TextField:
            info.edit_buffer = descriptor

        return info.wid

    def destroyWidget(self, wid: XPWidgetID, destroy_children: int = 1) -> None:
        """
        XPWidgets API: destroy a widget.
        Delegates to WidgetManager.destroy_widget(), which handles subtree deletion,
        parent unlinking, z-order removal, focus clearing, backend deletion queueing,
        and XP→DPG dirtying.
        """
        self.wm.destroy_widget(wid)

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
        XPWidgets API: set widget geometry in global XP coordinates.
        Geometry is stored as WGeom; WindowExInfo handles dirtying.
        """
        info = self.wm.require_info(wid)
        info.geometry = WGeom(left, top, right, bottom)  # setter dirties window
        info.geom_applied = False
        info.container_geom_applied = None

    def getWidgetGeometry(self, wid: XPWidgetID) -> tuple[int, int, int, int]:
        """
        XPWidgets API: return authoritative XP geometry.
        """
        return self.wm.require_info(wid).geometry.as_tuple()

    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> tuple[int, int, int, int]:
        """
        XPWidgets API: exposed geometry is identical to stored geometry.
        """
        return self.getWidgetGeometry(wid)

    # ------------------------------------------------------------------
    # VISIBILITY
    # ------------------------------------------------------------------
    def showWidget(self, wid: XPWidgetID) -> None:
        """
        XPWidgets API: show widget.
        """
        info = self.wm.require_info(wid)
        info.set_visible(True)

    def hideWidget(self, wid: XPWidgetID) -> None:
        """
        XPWidgets API: hide widget.
        """
        info = self.wm.require_info(wid)
        info.set_visible(False)

    def isWidgetVisible(self, wid: XPWidgetID) -> bool:
        """
        XPWidgets API: return visibility state.
        """
        return bool(self.wm.require_info(wid).visible)

    # ------------------------------------------------------------------
    # PROPERTIES
    # ------------------------------------------------------------------
    def setWidgetProperty(
        self,
        wid: XPWidgetID,
        prop: XPWidgetPropertyID | int,
        value: Any,
    ) -> None:
        """
        XPWidgets API: set a widget property.
        """
        info = self.wm.require_info(wid)
        info.properties[prop] = value
        info.window._dirty_xp_to_dpg = True

    def getWidgetProperty(
        self,
        wid: XPWidgetID,
        prop: XPWidgetPropertyID | int,
    ) -> Any:
        """
        XPWidgets API: get a widget property.
        """
        return self.wm.require_info(wid).properties.get(prop)

    # ------------------------------------------------------------------
    # CALLBACKS + MESSAGE DISPATCH
    # ------------------------------------------------------------------
    def addWidgetCallback(self, wid: XPWidgetID, callback: XPWidgetCallback) -> None:
        info = self.wm.require_info(wid)
        if callback not in info.callbacks:
            info.callbacks.append(callback)

    def sendMessageToWidget(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage | int,
        param1: Any,
        param2: Any,
    ) -> None:
        """
        XPWidgets API: send a message to a widget, bubbling up the parent chain
        until a callback returns non-zero or the root is reached.
        """

        info = self.wm.require_info(wid)

        # 1. Deliver to this widget
        for cb in info.callbacks:
            try:
                result = cb(msg, wid, param1, param2)
            except Exception:
                result = 0

            if result:
                return None

        # 2. Bubble to parent
        if info.parent is not None:
            return self.sendMessageToWidget(info.parent, msg, param1, param2)

        return None

    def broadcastMessageToWidget(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage | int,
        param1: Any,
        param2: Any,
    ) -> None:
        """
        XPWidgets API: broadcast a message to a widget and its descendants.
        Propagation stops when a callback returns non-zero.
        """
        visited: set[XPWidgetID] = set()

        def _broadcast(current: XPWidgetID) -> bool:
            if current in visited:
                return False
            visited.add(current)

            info = self.wm.require_info(current)

            # Deliver to this widget first
            for cb in info.callbacks:
                try:
                    result = cb(current, msg, param1, param2)
                except Exception:
                    result = 0

                if result:
                    info.window._dirty_xp_to_dpg = True
                    return True

            # Then deliver to children
            for child in info.children:
                if _broadcast(child):
                    return True

            return False

        _broadcast(wid)

    # ------------------------------------------------------------------
    # HIERARCHY / HIT TESTING
    # ------------------------------------------------------------------
    def getParentWidget(self, wid: XPWidgetID) -> XPWidgetID | None:
        """
        XPWidgets API: return the parent widget ID, or None if root.
        """
        return self.wm.require_info(wid).parent

    def getWidgetForLocation(self, x: int, y: int) -> Optional[XPWidgetID]:
        """
        XPWidgets API: hit-test all windows front-to-back and return the topmost widget
        at (x, y) in window coordinates.

        NOTE: This assumes FakeXP can enumerate WindowExInfo instances and that
        (x, y) is already in the appropriate window's coordinate space.
        """
        # Frontmost windows last; we want topmost, so iterate reversed if needed.
        for win in self.fake_xp.window_manager.all_info():
            wid = self.wm.hit_test(win, x, y)
            if wid is not None:
                return wid
        return None

    # ------------------------------------------------------------------
    # Z‑ORDER
    # ------------------------------------------------------------------
    def isWidgetInFront(self, wid: XPWidgetID) -> bool:
        """
        XPWidgets API: return True if the widget is the frontmost in its window.
        """
        info = self.wm.require_info(wid)
        z = info.window.z_order
        return bool(z) and z[-1] == wid

    def bringWidgetToFront(self, wid: XPWidgetID) -> None:
        """
        XPWidgets API: raise widget to front within its window.
        """
        self.wm.raise_widget(wid)

    def pushWidgetBehind(self, wid: XPWidgetID) -> None:
        """
        XPWidgets API: send widget to back within its window.
        """
        self.wm.lower_widget(wid)

    # ------------------------------------------------------------------
    # KEYBOARD FOCUS
    # ------------------------------------------------------------------
    def getKeyboardFocus(self) -> XPWidgetID | None:
        """
        XPWidgets API: return the widget with keyboard focus, if any.

        Semantics: returns the focused widget of the frontmost window that has focus,
        or None if no window has a focused widget.
        """
        for win in self.fake_xp.window_manager.all_info():
            if win.focused_widget is not None:
                return win.focused_widget
        return None

    def setKeyboardFocus(self, wid: XPWidgetID) -> None:
        """
        XPWidgets API: give keyboard focus to a widget.
        """
        self.wm.set_focus(wid)

    def loseKeyboardFocus(self, wid: XPWidgetID) -> None:
        """
        XPWidgets API: remove keyboard focus from a widget if it currently has it.
        """
        info = self.wm.require_info(wid)
        if info.window.focused_widget == wid:
            self.wm.clear_focus(info.window)

    # ------------------------------------------------------------------
    # DESCRIPTOR / CLASS
    # ------------------------------------------------------------------
    def getWidgetDescriptor(self, wid: XPWidgetID) -> str:
        """
        XPWidgets API: get the widget's descriptor string.
        """
        return self.wm.require_info(wid).descriptor

    def setWidgetDescriptor(self, wid: XPWidgetID, text: str) -> None:
        """
        XPWidgets API: set the widget's descriptor string.
        """
        info = self.wm.require_info(wid)
        info.set_descriptor(text)

    def getWidgetClass(self, wid: XPWidgetID) -> XPWidgetClass:
        """
        XPWidgets API: get the widget's class.
        """
        return self.wm.require_info(wid).widget_class

    def getWidgetUnderlyingWindow(self, wid: XPWidgetID) -> int:
        """
        XPWidgets API: return the underlying XPLM window ID for this widget's window.
        """
        info = self.wm.require_info(wid)
        return int(info.window.wid)
