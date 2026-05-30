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

from typing import Any, cast, Literal, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import XPPoint, XPGeom, XPWidgetCallback, WindowExInfo
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
        isRoot: int,
        container: XPWidgetID | Literal[0],
        widgetClass: XPWidgetClass,
    ) -> XPWidgetID:

        abs_geom = XPGeom(left, top, right, bottom)
        visible_bool = bool(visible)

        # ---------------------------------------------------------
        # ROOT WIDGET
        # ---------------------------------------------------------
        if isRoot:
            if container != 0:
                raise ValueError(f"Root widget must have container=0 (got {container})")

            return self._create_root_widget_window(
                xp_geom=abs_geom,
                descriptor=descriptor,
                widgetClass=widgetClass,
                visible=visible_bool,
            )

        # ---------------------------------------------------------
        # NON-ROOT WIDGET
        # ---------------------------------------------------------
        if container == 0:
            raise ValueError("Non-root widget cannot have container=0")

        parent_wid = XPWidgetID(container)
        parent_info = self.wm.require_info(parent_wid)
        window_info = parent_info.window

        # geometry=abs_geom → WidgetInfo converts to local internally
        info = self.wm.create_widget(
            widget_class=widgetClass,
            window=window_info,
            abs_geom=abs_geom,
            parent=parent_wid,
            descriptor=descriptor,
            visible=visible_bool,
        )

        # Text field selection properties
        if widgetClass == self.fake_xp.WidgetClass_TextField:
            info.set_property(self.fake_xp.Property_EditFieldSelStart, 0)
            info.set_property(self.fake_xp.Property_EditFieldSelEnd, 0)

        return info.wid

    def _create_root_widget_window(self, xp_geom, descriptor, widgetClass, visible):

        # Create XPLM-style window using ABSOLUTE XPGeom
        win_info = self.fake_xp.window_manager.create_window(
            left=xp_geom.left,
            top=xp_geom.top,
            right=xp_geom.right,
            bottom=xp_geom.bottom,
            visible=visible,
            decoration=self.fake_xp.WindowDecorationRoundRectangle,
            layer=self.fake_xp.WindowLayerFloatingWindows,
            no_title_bar=True,
        )

        # ---------------------------------------------------------
        # ROOT WIDGET
        # ---------------------------------------------------------
        # Root widget uses the CLIENT RECT as its ABSOLUTE geometry.
        # WidgetInfo will convert this to local_xpgeom = (0,0,w,h)
        root_info = self.wm.create_widget(
            widget_class=widgetClass,
            window=win_info,
            abs_geom=win_info.client,
            parent=None,
            descriptor=descriptor,
            visible=visible,
        )

        win_info.set_widget_root(root_info.wid)

        # ---------------------------------------------------------
        # TITLE BAR (absolute coords inside client)
        # ---------------------------------------------------------
        title_h = WindowExInfo.TITLE_BAR_HEIGHT

        title_geom = XPGeom(
            left=win_info.client.left + 4,
            top=win_info.client.top - 4,
            right=win_info.client.right - 4,
            bottom=win_info.client.top - 4 - title_h,
        )

        self.wm.create_widget(
            widget_class=self.fake_xp.WidgetClass_Caption,
            window=win_info,
            abs_geom=title_geom,  # ABSOLUTE XPGeom
            parent=root_info.wid,
            descriptor=descriptor,
            visible=True,
        )

        # ---------------------------------------------------------
        # CLOSE BUTTON (absolute coords inside client)
        # ---------------------------------------------------------
        close_size = WindowExInfo.CLOSE_BOX_SIZE
        close_geom = XPGeom(
            left=win_info.client.right - close_size - 4,
            top=win_info.client.top - 4,
            right=win_info.client.right - 4,
            bottom=win_info.client.top - 4 - close_size,
        )
        close_info = self.wm.create_widget(
            widget_class=self.fake_xp.WidgetClass_Button,
            window=win_info,
            abs_geom=close_geom,
            parent=root_info.wid,
            descriptor="X",
            visible=False,
        )
        # Attach close-button callback
        close_info.add_callback(
            self._close_button_handler
        )
        win_info._close_widget = close_info.wid

        return root_info.wid

    def _close_button_handler(self, msg, wid, p1, p2):
        """
        Callback for the custom close button widget.

        - Fires on xpMsg_PushButtonPressed.
        - Sends xpMessage_CloseButtonPushed to the parent widget (root).
        - Does NOT destroy anything directly.
        """

        if msg == self.fake_xp.Msg_PushButtonPressed:
            wm = self.fake_xp.widget_manager
            info = wm.require_info(wid)

            parent = info.parent
            if parent is not None:
                wm.queue_msg(
                    parent,
                    self.fake_xp.Message_CloseButtonPushed,
                    wid,  # p1 = close button widget ID
                    0  # p2 unused
                )

            return 1  # handled

        return 0  # not handled

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
        info.set_local_geom(XPGeom(left, top, right, bottom))

    def getWidgetGeometry(self, wid: XPWidgetID) -> tuple[int, int, int, int]:
        """
        XPWidgets API: return authoritative XP geometry.
        """
        geom = self.wm.require_info(wid).abs_xpgeom
        return geom.left, geom.top, geom.right, geom.bottom

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
        self, widgetID: XPWidgetID, propertyID: XPWidgetPropertyID | int, exists: Optional[int] = None
    ) -> Any:
        """
        XPWidgets API: get a widget property.
        """
        return self.wm.require_info(widgetID).properties.get(propertyID)

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
        XPWidgets API: send a message to a widget.
        Dispatching is handled entirely by the widget manager.
        """
        self.wm.queue_msg(wid, msg, param1, param2)

    def broadcastMessageToWidget(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage | int,
        param1: Any,
        param2: Any,
    ) -> None:
        """
        XPWidgets API: broadcast a message to a widget and all descendants.
        Each widget receives a full dispatch cycle (plugin → parent.plugin → default).
        """

        visited: set[XPWidgetID] = set()

        def _broadcast(current: XPWidgetID):
            if current in visited:
                return
            visited.add(current)

            # Dispatch to this widget
            self.wm.queue_msg(current, msg, param1, param2)

            # Recurse into children
            info = self.wm.require_info(current)
            for child in info.children:
                _broadcast(child)

        _broadcast(wid)

    # ------------------------------------------------------------------
    # HIERARCHY / HIT TESTING
    # ------------------------------------------------------------------
    def getParentWidget(self, wid: XPWidgetID) -> XPWidgetID | None:
        """
        XPWidgets API: return the parent widget ID, or None if root.
        """
        return self.wm.require_info(wid).parent

    def getWidgetForLocation(
        self,
        wid: XPWidgetID,
        x: int,
        y: int,
        recursive: int,
    ) -> Optional[XPWidgetID]:
        """
        XPWidgets API: return the topmost widget at (x, y) under the given root.
        Coordinates are in the window's GLOBAL coordinate system.
        """

        info = self.wm.require_info(wid)
        xp_pt = XPPoint(x, y)

        # 1. Hit test this widget using GLOBAL geometry
        if not info.abs_xpgeom.contains(xp_pt):
            return None

        # 2. If recursive, search children in front-to-back order
        if recursive:
            for child in reversed(info.children):
                hit = self.getWidgetForLocation(child, x, y, 1)
                if hit is not None:
                    return hit

        # 3. No child hit → this widget is the hit
        return wid

    # ------------------------------------------------------------------
    # Z‑ORDER
    # ------------------------------------------------------------------
    def isWidgetInFront(self, wid: XPWidgetID) -> bool:
        """
        XPWidgets API: return True if the widget is the frontmost in its window.
        """
        info = self.wm.require_info(wid)
        z = info.window.widget_z_order
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
        self.wm.clear_focus(wid)

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
