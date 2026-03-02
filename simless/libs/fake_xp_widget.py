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

from typing import Any, Dict, List, Optional, Tuple

from simless.libs.fake_xp_interface import FakeXPInterface
from simless.libs.fake_xp_types import WidgetInfo
from simless.libs.fake_xp_widget_api import FakeXPWidgetsAPI
from XPPython3.xp_typing import XPWidgetID


class FakeXPWidget(FakeXPWidgetsAPI):
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
        "all_widget_ids",
        "map_widgets_to_dpg",
        "render_widget_frame",
    ]

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
            if info.parent == XPWidgetID(0):
                self._dispatch_draw(wid)

        self._needs_redraw = False

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
            return

        xp = self.xp
        wclass = info.widget_class
        desc = info.descriptor

        is_window = wclass in (
            xp.WidgetClass_MainWindow,
            xp.WidgetClass_SubWindow,
        )

        # ------------------------------------------------------------
        # XP WINDOWS -> real top-level DPG windows (siblings)
        # ------------------------------------------------------------
        if is_window:
            dpg_id = self.xp.dpg_add_window(
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

        if parent_wid == XPWidgetID(0):
            raise RuntimeError(f"[Create] wid={wid} ERROR: control has no parent")

        # Ensure parent window exists first
        self._ensure_dpg_item_for_widget(parent_wid)

        parent_info = self._widgets.get(parent_wid)
        parent_container = parent_info.container_id if parent_info else None

        if parent_container is None:
            raise RuntimeError(f"[Create] wid={wid} ERROR: parent container invalid")

        # Create / reuse the positionable container for this control
        cont = info.container_id
        if cont is None:
            cont = self.xp.dpg_add_child_window(
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
            dpg_id = self.xp.dpg_add_text(
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

            dpg_id = self.xp.dpg_add_input_text(
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

            dpg_id = self.xp.dpg_add_slider_int(
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

            dpg_id = self.xp.dpg_add_button(
                label=desc or "",
                parent=cont,
                callback=_on_button,
                user_data=wid,
            )

        else:
            dpg_id = self.xp.dpg_add_text(
                desc or f"Widget {wid}",
                parent=cont,
            )

        info.dpg_id = dpg_id

    def _render_widgets(self) -> None:
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
                self.xp.dpg_configure_item(info.dpg_id, pos=(x, top - h), width=w, height=h)
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
            self.xp.dpg_configure_item(info.container_id, pos=(lx, ly), width=w, height=h)
            info.container_geom_applied = desired

    def _apply_visibility(self, wid: XPWidgetID) -> None:
        """Apply XP visibility to the DPG representation (write-only)."""
        info = self._require_widget(wid)

        # If not created yet, nothing to show/hide.
        if info.container_id is None:
            return

        if info.visible:
            self.xp.dpg_show_item(info.container_id)
        else:
            self.xp.dpg_hide_item(info.container_id)

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
            cb(self.xp.Msg_Draw, wid, wid, None)

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

        self.xp.dpg_set_value(info.dpg_id, int(value))
        return None
