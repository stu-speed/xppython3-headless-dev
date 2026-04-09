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

from typing import Any, List, Optional, Tuple

from simless.libs.fake_xp_types import DPGOp, WidgetInfo, WindowExInfo
from simless.libs.fake_xp_widget_api import FakeXPWidgetsAPI
from XPPython3.xp_typing import XPWidgetID, XPWidgetPropertyID


class FakeXPWidget(FakeXPWidgetsAPI):
    # ------------------------------------------------------------------
    # INITIALIZATION
    # ------------------------------------------------------------------

    def _init_widgets(self) -> None:
        """Initialize all internal XPWidget bookkeeping structures."""
        self._z_order: List[XPWidgetID] = []
        self._focused_widget: Optional[XPWidgetID] = None

        self._widgets_dirty = True
        self._widgets_initialized = False

        self._next_id = 1

    # -------------------------
    # helpers
    # -------------------------
    def _get_widget(self, wid: XPWidgetID) -> WidgetInfo:
        """
        Fail-fast lookup for a widget.

        - Ensures the widget belongs to a WindowEx
        - Ensures the widget exists in that WindowEx
        - Returns the WidgetInfo
        - Never returns None
        """
        win = self._get_widget_windowex(wid)  # fail fast if not found

        try:
            info = win.widgets[wid]
        except KeyError:
            raise KeyError(f"Widget {wid} does not exist") from None

        if info is None:
            raise RuntimeError(f"Internal error: Widget {wid} mapped to None")

        return info

    def _get_widget_windowex(self, wid: XPWidgetID) -> WindowExInfo:
        """
        Return the WindowExInfo that owns the given widget.

        Fail fast:
        - If no WindowEx contains this widget, raise a clear exception.
        """
        for win in self.fake_xp.window_manager.all_info():
            if wid in win.widgets:
                return win

        raise KeyError(f"Widget {wid} does not belong to any WindowEx")

    def _update_widget(
        self,
        info: WidgetInfo,
        *,
        visible: bool | None = None,
        descriptor: str | None = None,
        prop: tuple[XPWidgetPropertyID, Any] | None = None,
    ) -> None:
        """
        Centralized backend update helper.
        - Updates the WidgetInfo object
        - Enqueues only the backend commands needed for the specific change
        - Marks widget layer dirty
        """

        # ------------------------------------------------------------
        # Visibility
        # ------------------------------------------------------------
        if visible is not None:
            info.visible = bool(visible)
            if info.container_id is not None:
                if info.visible:
                    self.gm.enqueue_dpg(DPGOp.SHOW_ITEM, args=(info.container_id,))
                else:
                    self.gm.enqueue_dpg(DPGOp.HIDE_ITEM, args=(info.container_id,))

        # ------------------------------------------------------------
        # Descriptor
        # ------------------------------------------------------------
        if descriptor is not None:
            info.descriptor = descriptor
            if info.dpg_id is not None:
                desc = descriptor or ""
                if info.widget_class == self.fake_xp.WidgetClass_TextField:
                    self.gm.enqueue_dpg(
                        DPGOp.SET_VALUE,
                        args=(info.dpg_id,),
                        kwargs=dict(value=desc.strip()),
                    )
                elif info.widget_class == self.fake_xp.WidgetClass_Caption:
                    self.gm.enqueue_dpg(
                        DPGOp.SET_VALUE,
                        args=(info.dpg_id,),
                        kwargs=dict(value=desc),
                    )
                elif info.widget_class == self.fake_xp.WidgetClass_Button:
                    self.gm.enqueue_dpg(
                        DPGOp.CONFIGURE_ITEM,
                        args=(info.dpg_id,),
                        kwargs=dict(label=desc),
                    )

        # ------------------------------------------------------------
        # Scrollbar properties
        # ------------------------------------------------------------
        if prop is not None:
            prop_id, new_val = prop
            info.properties[prop_id] = new_val

            if info.widget_class == self.fake_xp.WidgetClass_ScrollBar and info.dpg_id is not None:
                if prop_id == self.fake_xp.Property_ScrollBarMin:
                    self.gm.enqueue_dpg(
                        DPGOp.CONFIGURE_ITEM,
                        args=(info.dpg_id,),
                        kwargs=dict(min_value=int(new_val)),
                    )
                elif prop_id == self.fake_xp.Property_ScrollBarMax:
                    self.gm.enqueue_dpg(
                        DPGOp.CONFIGURE_ITEM,
                        args=(info.dpg_id,),
                        kwargs=dict(max_value=int(new_val)),
                    )
                elif prop_id == self.fake_xp.Property_ScrollBarSliderPosition:
                    self.gm.enqueue_dpg(
                        DPGOp.SET_VALUE,
                        args=(info.dpg_id,),
                        kwargs=dict(value=int(new_val)),
                    )

        # ------------------------------------------------------------
        # Mark widget layer dirty
        # ------------------------------------------------------------
        self._widgets_dirty = True

    def _kill_widget(self, wid: XPWidgetID) -> None:
        """
        Destroy a widget and its entire subtree.

        If this widget is the root of a WindowEx, destroy the entire WindowEx.
        Structural only: backend deletions are queued, never executed directly.
        """

        # --------------------------------------------------------------
        # 0. Detect if this widget is the WindowEx root
        # --------------------------------------------------------------
        win = self._get_widget_windowex(wid)
        if win.widget_root == wid: # Destroy ALL widgets in this WindowEx (including root)
            for child_wid in list(win.widgets.keys()):
                if child_wid != wid:
                    self._kill_widget(child_wid)

            # Remove root widget from registry
            win.widgets.pop(wid, None)
            win.set_widget_root(None)

            # Now that the WindowEx has NO widgets, destroy the WindowEx
            self.fake_xp.destroyWindow(win.wid)
            return

        # --------------------------------------------------------------
        # 1. Fail-fast: ensure widget exists
        # --------------------------------------------------------------
        info = self._get_widget(wid)

        # --------------------------------------------------------------
        # 2. Recursively destroy children
        # --------------------------------------------------------------
        for child_wid in list(info.children):
            self._kill_widget(child_wid)

        # --------------------------------------------------------------
        # 3. Queue DPG deletions (never execute directly)
        # --------------------------------------------------------------
        if info.dpg_id is not None:
            self.gm.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.dpg_id,))

        if info.container_id is not None and info.container_id != info.dpg_id:
            self.gm.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.container_id,))

        # --------------------------------------------------------------
        # 4. Remove from parent's children list
        # --------------------------------------------------------------
        if info.parent is not None:
            parent_info = self._get_widget(info.parent)
            try:
                parent_info.children.remove(wid)
            except ValueError:
                raise RuntimeError(
                    f"Internal error: parent {info.parent} does not list child {wid}"
                )

        # --------------------------------------------------------------
        # 5. Remove from WindowEx registry
        # --------------------------------------------------------------
        win.widgets.pop(wid, None)

        # --------------------------------------------------------------
        # 6. Remove from z-order
        # --------------------------------------------------------------
        if wid in self._z_order:
            self._z_order.remove(wid)

        # --------------------------------------------------------------
        # 7. Clear focus if needed
        # --------------------------------------------------------------
        if self._focused_widget == wid:
            self._focused_widget = None

        # --------------------------------------------------------------
        # 8. Mark redraw
        # --------------------------------------------------------------
        self._widgets_dirty = True

    def map_widgets_to_dpg(self) -> None:
        """
        Structural realization + normalization pass.

        Runs whenever `_widgets_initialized` is False. This occurs once before the
        first frame and again whenever widgets are created dynamically.

        Responsibilities:
          - Realize all widgets by ensuring each has a DPG representation
            (`_ensure_dpg_item_for_widget`), without applying geometry or backend
            updates.
          - Normalize XP window geometry so each window encloses all visible
            descendants.
          - Mark initialization complete.

        Notes:
          - This pass is structural only. Geometry and backend updates are applied
            later during `_render_widgets()` when `_widgets_dirty` is True.
          - Dynamic creation sets `_widgets_initialized = False`, causing this pass
            to run again on the next frame.
        """

        if self._widgets_initialized:
            return

        # 1. Realize all widgets (per WindowEx)
        for win in self.fake_xp.window_manager.all_info():
            for wid in win.widgets:
                self._ensure_dpg_item_for_widget(wid)

        # 2. Normalize XP window geometry
        self._normalize_window_geometry_descendants()

        # 3. Initialization complete
        self._widgets_initialized = True

    def render_widget_frame(self) -> None:
        """
        Per-frame XPWidgets rendering pass.

        Responsibilities:
          - If `_widgets_dirty` is True, apply geometry, visibility, and any queued
            backend updates via `_render_widgets()`.
          - Always dispatch draw callbacks for each WindowEx root widget.
            Draw callbacks may mutate widget state and set `_widgets_dirty` for the
            *next* frame.
          - Clear `_widgets_dirty` only after geometry/visibility updates have been
            applied this frame.

        Notes:
          - This method never performs structural realization. That occurs in
            `map_widgets_to_dpg()` when `_widgets_initialized` is False.
          - Draw callbacks always run, even when no geometry changed, matching
            X‑Plane’s rendering semantics.
        """

        # Apply geometry + visibility + backend updates (queued → flushed)
        if self._widgets_dirty:
            self._render_widgets()
            self._widgets_dirty = False

        # Dispatch draw callbacks for each WindowEx root
        for win in self.fake_xp.window_manager.all_info():
            root = win.widget_root
            info = win.widgets.get(root)
            if info and info.dpg_id is not None:
                self._dispatch_draw(root)

    # ------------------------------------------------------------------
    # RENDERING
    # ------------------------------------------------------------------

    def _normalize_window_geometry_descendants(self) -> None:
        """
        One-time XP compatibility pass.

        Expand each XP window (MainWindow or SubWindow) to fully contain the
        bounding box of all *visible descendant widgets*, using XP geometry:

            geometry = (left, top, right, bottom)
            width  = right - left
            height = top - bottom
        """

        def iter_descendants(win, root):
            """Yield all descendant widget IDs inside this WindowEx."""
            for child_id, child in win.widgets.items():
                if child.parent == root:
                    yield child_id
                    yield from iter_descendants(win, child_id)

        # Iterate per WindowEx (correct architecture)
        for win in self.fake_xp.window_manager.all_info():
            for wid, info in win.widgets.items():
                # Only normalize XP windows
                if info.widget_class not in (
                        self.fake_xp.WidgetClass_MainWindow,
                        self.fake_xp.WidgetClass_SubWindow,
                ):
                    continue

                # XP geometry: (left, top, right, bottom)
                left, top, right, bottom = info.geometry

                # Initial extents are the window's own extents
                max_right = right
                min_bottom = bottom

                # Walk all descendants inside this WindowEx
                for child_id in iter_descendants(win, wid):
                    if not self.isWidgetVisible(child_id):
                        continue

                    child = win.widgets.get(child_id)
                    if child is None:
                        continue

                    cleft, ctop, cright, cbottom = child.geometry

                    max_right = max(max_right, cright)
                    min_bottom = min(min_bottom, cbottom)

                # Compute new window size (XP semantics)
                old_w = right - left
                old_h = top - bottom

                new_w = max_right - left
                new_h = top - min_bottom

                if new_w > old_w or new_h > old_h:
                    self.fake_xp.log(
                        f"[Normalize] window wid={wid} "
                        f"expanded from {old_w}x{old_h} to {new_w}x{new_h}"
                    )

                    # Update XP geometry (structural only)
                    info.geometry = (
                        left,
                        top,
                        left + new_w,
                        top - new_h,
                    )

                    # Force geometry to be re-applied next render pass
                    info.geom_applied = False
                    self._widgets_dirty = True

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

        This performs *structural realization only* and queues all backend
        operations via self.gm.enqueue_dpg(). No backend commands are executed
        immediately.

        Preconditions:
          - XPWidget exists in its owning WindowEx
          - Parent widgets must be realized before children
        """

        info = self._require_widget(wid)

        # Already realized?
        if info.dpg_id is not None:
            return

        wclass = info.widget_class
        desc = info.descriptor or ""

        # Deterministic backend IDs
        dpg_id = f"xp_widget_{wid}"
        container_id = f"xp_widget_container_{wid}"

        is_window = wclass in (
            self.fake_xp.WidgetClass_MainWindow,
            self.fake_xp.WidgetClass_SubWindow,
        )

        # ------------------------------------------------------------
        # XP WINDOWS → top-level DPG windows
        # ------------------------------------------------------------
        if is_window:
            self.gm.enqueue_dpg(
                op=DPGOp.ADD_WINDOW,
                kwargs=dict(
                    tag=dpg_id,
                    label=desc or "Window",
                    width=200,
                    height=100,
                    no_scrollbar=True,
                    no_collapse=True,
                    no_resize=False,
                    no_move=False,
                ),
            )

            info.dpg_id = dpg_id
            info.container_id = dpg_id
            info.geom_applied = False
            info.container_geom_applied = None
            return

        # ------------------------------------------------------------
        # XP CONTROLS → child_window inside parent window
        # ------------------------------------------------------------
        parent_wid = info.parent
        if parent_wid is None:
            raise RuntimeError(f"[Create] wid={wid} ERROR: control has no parent")

        # Ensure parent is realized first
        self._ensure_dpg_item_for_widget(parent_wid)

        parent_info = self._require_widget(parent_wid)
        parent_container = parent_info.container_id
        if parent_container is None:
            raise RuntimeError(f"[Create] wid={wid} ERROR: parent container invalid")

        # Create container if needed
        if info.container_id is None:
            self.gm.enqueue_dpg(
                op=DPGOp.ADD_CHILD_WINDOW,
                kwargs=dict(
                    tag=container_id,
                    parent=parent_container,
                    width=20,
                    height=10,
                    no_scrollbar=True,
                    border=False,
                    autosize_x=False,
                    autosize_y=False,
                ),
            )
            info.container_id = container_id
            info.container_geom_applied = None

        # ------------------------------------------------------------
        # Create actual control
        # ------------------------------------------------------------
        if wclass == self.fake_xp.WidgetClass_Caption:
            self.gm.enqueue_dpg(
                op=DPGOp.ADD_TEXT,
                kwargs=dict(
                    tag=dpg_id,
                    default_value=desc.strip(),
                    parent=info.container_id,
                ),
            )

        elif wclass == self.fake_xp.WidgetClass_TextField:
            def _on_text(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                w = self._require_widget(widget_id)
                w.edit_buffer = app_data
                self.sendMessageToWidget(
                    widget_id,
                    self.fake_xp.Msg_TextFieldChanged,
                    widget_id,
                    app_data,
                )

            self.gm.enqueue_dpg(
                op=DPGOp.ADD_INPUT_TEXT,
                kwargs=dict(
                    tag=dpg_id,
                    default_value=desc.strip(),
                    parent=info.container_id,
                    callback=_on_text,
                    user_data=wid,
                    no_spaces=True,
                ),
            )

        elif wclass == self.fake_xp.WidgetClass_ScrollBar:
            min_v = int(self.getWidgetProperty(wid, self.fake_xp.Property_ScrollBarMin) or 0)
            max_v = int(self.getWidgetProperty(wid, self.fake_xp.Property_ScrollBarMax) or 100)
            cur_v = int(
                self.getWidgetProperty(wid, self.fake_xp.Property_ScrollBarSliderPosition)
                or min_v
            )

            def _on_scroll(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                new_pos = int(app_data)
                self.setWidgetProperty(
                    widget_id,
                    self.fake_xp.Property_ScrollBarSliderPosition,
                    new_pos,
                )
                self.sendMessageToWidget(
                    widget_id,
                    self.fake_xp.Msg_ScrollBarSliderPositionChanged,
                    widget_id,
                    new_pos,
                )

            self.gm.enqueue_dpg(
                op=DPGOp.ADD_SLIDER_INT,
                kwargs=dict(
                    tag=dpg_id,
                    label=desc or "Slider",
                    parent=info.container_id,
                    min_value=min_v,
                    max_value=max_v,
                    default_value=cur_v,
                    callback=_on_scroll,
                    user_data=wid,
                ),
            )

        elif wclass == self.fake_xp.WidgetClass_Button:
            def _on_button(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                self.sendMessageToWidget(
                    widget_id,
                    self.fake_xp.Msg_PushButtonPressed,
                    widget_id,
                    None,
                )

            self.gm.enqueue_dpg(
                op=DPGOp.ADD_BUTTON,
                kwargs=dict(
                    tag=dpg_id,
                    label=desc,
                    parent=info.container_id,
                    callback=_on_button,
                    user_data=wid,
                ),
            )

        else:
            self.gm.enqueue_dpg(
                op=DPGOp.ADD_TEXT,
                kwargs=dict(
                    tag=dpg_id,
                    default_value=desc or f"Widget {wid}",
                    parent=info.container_id,
                ),
            )

        info.dpg_id = dpg_id

    def _render_widgets(self) -> None:
        """
        Apply geometry and backend updates for all widgets in all WindowEx instances.
        """
        # Iterate per-window, because widgets now live inside WindowExInfo
        for win in self.fake_xp.window_manager.all_info():
            for wid, info in list(win.widgets.items()):
                # Geometry is applied exactly once per change
                self._apply_geometry_if_needed(wid)

                # Visibility is applied if changed
                self._apply_visibility(wid)

    # ------------------------------------------------------------------
    # GEOMETRY APPLICATION (DPG WRITE‑ONLY)
    # ------------------------------------------------------------------

    def _apply_geometry_if_needed(self, wid: XPWidgetID) -> None:
        """
        Queue geometry updates for this widget if its XP geometry changed.

        This method computes the correct DPG geometry for the widget and enqueues
        the appropriate backend command, but does *not* execute it. Geometry
        application is write-only and idempotent: repeated calls with unchanged
        geometry are no-ops.

        Preconditions:
          - Widget must already be structurally realized (container_id exists)
          - Layout must be ready (geometry is meaningful)
        """

        info = self._require_widget(wid)

        # Nothing to apply until DPG objects exist
        if info.container_id is None:
            return

        left, top, right, bottom = info.geometry
        width = right - left
        height = top - bottom

        # --------------------------------------------------
        # Top-level XP windows → configure the DPG window
        # --------------------------------------------------
        if info.widget_class in (
                self.fake_xp.WidgetClass_MainWindow,
                self.fake_xp.WidgetClass_SubWindow,
        ):
            if info.dpg_id is None:
                raise RuntimeError(
                    f"_apply_geometry_if_needed: window wid={wid} has no dpg_id"
                )

            if not info.geom_applied:
                # Queue, do not execute
                self.gm.enqueue_dpg(
                    op=DPGOp.CONFIGURE_ITEM,
                    args=(info.dpg_id,),
                    kwargs=dict(
                        pos=(left, top - height),
                        width=width,
                        height=height,
                    ),
                )
                info.geom_applied = True

            return

        # --------------------------------------------------
        # Controls → configure their child_window container
        # --------------------------------------------------
        parent = info.parent
        if parent == XPWidgetID(0):
            raise RuntimeError(
                f"_apply_geometry_if_needed: control wid={wid} has no parent"
            )

        pinfo = self._require_widget(parent)
        pleft, ptop, _, _ = pinfo.geometry

        lx = left - pleft
        ly = ptop - top

        desired = (lx, ly, width, height)
        last = info.container_geom_applied

        if last != desired:
            # Queue, do not execute
            self.gm.enqueue_dpg(
                op=DPGOp.CONFIGURE_ITEM,
                args=(info.container_id,),
                kwargs=dict(
                    pos=(lx, ly),
                    width=width,
                    height=height,
                ),
            )
            info.container_geom_applied = desired

    def _apply_visibility(self, wid: XPWidgetID) -> None:
        """
        Queue visibility updates for this widget.

        Visibility is write-only and does not require layout readiness.
        If the widget has not yet been structurally realized (container_id is None),
        this is a no-op.

        All backend operations are queued via self.gm.enqueue_dpg() and executed later
        during the render pass. No backend commands are executed immediately.
        """

        info = self._require_widget(wid)

        # If not created yet, nothing to show/hide
        if info.container_id is None:
            return

        if info.visible:
            self.gm.enqueue_dpg(
                op=DPGOp.SHOW_ITEM,
                args=(info.container_id,),
            )
        else:
            self.gm.enqueue_dpg(
                op=DPGOp.HIDE_ITEM,
                args=(info.container_id,),
            )

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
            cb(self.fake_xp.Msg_Draw, wid, wid, None)
