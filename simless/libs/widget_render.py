# widget_render.py

from __future__ import annotations

from typing import Any, cast, Dict, TYPE_CHECKING

from simless.libs.fake_xp_types import DPGGeom, DPGOp, WidgetInfo, WindowExInfo
from XPPython3.xp_typing import XPWidgetID, XPWidgetMessage

if TYPE_CHECKING:
    from simless.libs.widget import WidgetManager


class WidgetRender:
    _widgets: Dict[XPWidgetID, WidgetInfo]
    _next_widget_id: int
    _msg_queue: list[tuple[XPWidgetID, XPWidgetMessage, Any, Any]]

    @property
    def mgr(self) -> WidgetManager:
        return cast("WidgetManager", cast(object, self))

    def render_widget_frame(self) -> None:
        """
        Per-frame XPWidgets rendering pass.

        Responsibilities:
          - If a WindowEx has _dirty_widgets=True, apply geometry, visibility,
            and structural realization via _render_widgets(win).
          - Always dispatch draw callbacks for each WindowEx root widget.
            Draw callbacks may mutate widget state and set _dirty_widgets for
            the *next* frame.
          - Clear _dirty_widgets only after geometry/visibility updates have
            been applied for that window.

        Notes:
          - This method never performs window-level XP→DPG sync (frame, layer,
            decoration). That is handled by the window manager.
          - Draw callbacks always run, even when no geometry changed, matching
            X‑Plane’s rendering semantics.
        """

        # ------------------------------------------------------------
        # 1. XP → DPG sync for widget trees (per-window)
        # ------------------------------------------------------------
        for win in self.mgr.fake_xp.window_manager.all_info():
            if win._dirty_widgets:
                self._render_widgets(win)
                win._dirty_widgets = False

        # ------------------------------------------------------------
        # 2. Dispatch draw callbacks (always)
        # ------------------------------------------------------------
        for win in self.mgr.wm.all_info():
            root = win.widget_root
            if root is not None:
                self._dispatch_draw(root)

    def _dispatch_draw(self, wid: XPWidgetID) -> None:
        """
        Dispatch draw callbacks for a top-level XP window.
        XP semantics:
          - Only root widgets receive Msg_Draw.
          - Draw callbacks may mutate widget state.
        """

        info = self.mgr.require_info(wid)

        # Only root widgets should receive draw callbacks
        if info.window.widget_root != wid:
            return

        for cb in info.callbacks:
            cb(self.mgr.fake_xp.Msg_Draw, wid, wid, None)

    def _render_widgets(self, win: WindowExInfo):
        for info in self.mgr.iter_window_widgets(win):
            wid = info.wid

            # 1. Ensure DPG structure exists
            self._ensure_dpg_item_for_widget(wid)

            # 2. Geometry
            self._apply_geometry(wid)

            # 3. Visibility
            self._apply_visibility(wid)

            # 4. Descriptor text
            self._apply_descriptor(wid)

            # 5. Widget properties (scrollbar min/max/value, etc.)
            self._apply_properties(wid)

    def _ensure_dpg_item_for_widget(self, wid: XPWidgetID) -> None:
        """
        Ensure that a DearPyGui representation exists for the given XPWidget.
        Structural only: queue backend ops, do not execute immediately.
        """

        info = self.mgr.require_info(wid)

        # Already realized?
        if info.dpg_id is not None and info.container_id is not None:
            return

        wclass = info.widget_class
        desc = info.descriptor or ""

        # ============================================================
        # MAIN WINDOW → bind to existing createWindowEx DPG window
        # ============================================================
        if wclass == self.mgr.fake_xp.WidgetClass_MainWindow:
            win = info.window  # WindowExInfo

            # createWindowEx already enqueued ADD_WINDOW + ADD_DRAWLIST
            info.dpg_id = win.dpg_tag
            info.container_id = win.dpg_tag  # root has window for the container
            info.container_geom_applied = None
            return

        # ============================================================
        # ALL NON-ROOT WIDGETS
        # XP widgets need absolute positioning + clipping.
        # Only mvChildWindow supports that in DPG.
        # Therefore every widget (including SubWindow) gets a child_window container.
        # ============================================================
        parent_wid = info.parent
        if parent_wid is None:
            raise RuntimeError(f"[Create] wid={wid} ERROR: control has no parent")

        # Ensure parent is realized first
        self._ensure_dpg_item_for_widget(parent_wid)

        parent_info = self.mgr.require_info(parent_wid)
        parent_container = parent_info.container_id
        if parent_container is None:
            raise RuntimeError(f"[Create] wid={wid} ERROR: parent container missing")

        # Apply XP auto-size rules
        self._apply_xp_autosize_rules(info, parent_info)

        # ------------------------------------------------------------
        # Create container (child_window)
        # ------------------------------------------------------------

        if info.container_id is None:
            info.container_id = f"xp_widget_container_{wid}"

            self.mgr.gm.enqueue_dpg(
                op=DPGOp.ADD_CHILD_WINDOW,
                kwargs=dict(
                    tag=info.container_id,
                    parent=parent_container,
                    width=20,
                    height=10,
                    no_scrollbar=True,
                    border=False,
                    autosize_x=False,
                    autosize_y=False,
                ),
            )
            info.container_geom_applied = False

        # ------------------------------------------------------------
        # Create actual control
        # ------------------------------------------------------------
        # Short‑circuit: if already created, stop immediately
        if info.dpg_id is not None:
            return

        # Assign deterministic ID before the type checks
        info.dpg_id = f"xp_widget_{wid}"

        # Now create the control for this widget class
        if wclass == self.mgr.fake_xp.WidgetClass_Caption:
            self.mgr.gm.enqueue_dpg(
                op=DPGOp.ADD_TEXT,
                kwargs=dict(
                    tag=info.dpg_id,
                    default_value=desc.strip(),
                    parent=info.container_id,
                ),
            )
        elif wclass == self.mgr.fake_xp.WidgetClass_TextField:
            is_editable = bool(info.callbacks)
            if not is_editable:
                # OUTPUT TEXTFIELD → DPG add_text
                self.mgr.gm.enqueue_dpg(
                    op=DPGOp.ADD_TEXT,
                    kwargs=dict(
                        tag=info.dpg_id,
                        default_value=desc.strip(),
                        parent=info.container_id,
                    ),
                )
                return

            # ---------------------------------------------------------
            # EDITABLE TEXTFIELD → DPG add_input_text
            # No per-keystroke callbacks.
            # Only Enter commits (on_enter=True).
            # ---------------------------------------------------------

            def _on_enter(sender, app_data, user_data):
                """
                Called ONLY when Enter is pressed.
                DPG has already updated the text buffer.
                XPWidgets should now lose focus and commit.
                """
                xp = self.mgr.fake_xp
                widget_id = XPWidgetID(user_data)

                # Queue xpMsg_KeyLoseFocus (processed later)
                xp.widget_manager.clear_focus(widget_id)

                key = 13 # enter key
                self.mgr.queue_msg(
                    info.wid,
                    self.mgr.fake_xp.Msg_KeyPress,
                    (key, self.mgr.fake_xp.input_manager.make_xp_flags(key), key),
                    0
                )

            self.mgr.gm.enqueue_dpg(
                op=DPGOp.ADD_INPUT_TEXT,
                kwargs=dict(
                    tag=info.dpg_id,
                    default_value=desc.strip(),
                    parent=info.container_id,
                    on_enter=True,  # Only Enter commits
                    callback=_on_enter,  # No per-keystroke updates
                    user_data=wid,
                    no_spaces=True,
                ),
            )

        elif wclass == self.mgr.fake_xp.WidgetClass_ScrollBar:
            min_v = info.properties.get(self.mgr.fake_xp.Property_ScrollBarMin, 0)
            max_v = info.properties.get(self.mgr.fake_xp.Property_ScrollBarMax, 100)
            cur_v = info.properties.get(
                self.mgr.fake_xp.Property_ScrollBarSliderPosition, min_v
            )

            def _on_scroll(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                new_pos = int(app_data)
                self.mgr.fake_xp.setWidgetProperty(
                    widget_id,
                    self.mgr.fake_xp.Property_ScrollBarSliderPosition,
                    new_pos,
                )
                self.mgr.fake_xp.sendMessageToWidget(
                    widget_id,
                    self.mgr.fake_xp.Msg_ScrollBarSliderPositionChanged,
                    widget_id,
                    new_pos,
                )

            self.mgr.gm.enqueue_dpg(
                op=DPGOp.ADD_SLIDER_INT,
                kwargs=dict(
                    tag=info.dpg_id,
                    label=desc or "Slider",
                    parent=info.container_id,
                    min_value=min_v,
                    max_value=max_v,
                    default_value=cur_v,
                    callback=_on_scroll,
                    user_data=wid,
                ),
            )

        elif wclass == self.mgr.fake_xp.WidgetClass_Button:
            def _on_button(sender, app_data, user_data):
                widget_id = XPWidgetID(user_data)
                self.mgr.fake_xp.sendMessageToWidget(
                    widget_id,
                    self.mgr.fake_xp.Msg_PushButtonPressed,
                    widget_id,
                    None,
                )

            self.mgr.gm.enqueue_dpg(
                op=DPGOp.ADD_BUTTON,
                kwargs=dict(
                    tag=info.dpg_id,
                    label=desc,
                    parent=info.container_id,
                    callback=_on_button,
                    user_data=wid,
                ),
            )

    def _apply_xp_autosize_rules(self, info, parent_info):
        """
        XPWidgets auto-size certain widget classes.
        FakeXP must emulate this behavior.
        """
        wclass = info.widget_class
        geom = info.abs_xpgeom
        parent_geom = parent_info.abs_xpgeom

        # Width of this widget as provided by plugin
        width = geom.right - geom.left

        # XP auto-expands captions, textfields, and buttons
        if wclass in (
                self.mgr.fake_xp.WidgetClass_Caption,
                self.mgr.fake_xp.WidgetClass_TextField,
                self.mgr.fake_xp.WidgetClass_Button,
        ):
            # XP rule: if width is small, expand to parent width
            if width < 100:  # threshold; XP uses "small width" heuristic
                geom.right = parent_geom.right

    def _apply_geometry(self, wid: XPWidgetID) -> None:
        """
        Apply XP → DPG geometry for this widget.

        XP side:
          - Widgets store only local_xpgeom (relative to window.client)
          - abs_xpgeom is computed on demand
          - Window movement automatically updates abs_xpgeom

        DPG side:
          - mvChildWindow does NOT auto-move when parent moves
          - So we must push abs_xpgeom into DPG every time geometry changes
        """

        info = self.mgr.require_info(wid)

        # Skip until DPG container exists
        if info.container_id is None:
            return

        # Root widget window geometry is handled by WindowExInfo
        if info.window.widget_root == wid:
            return

        # ------------------------------------------------------------
        # Compute DPG geometry using XPGeom helper
        # ------------------------------------------------------------
        abs_geom = info.abs_xpgeom  # XPGeom
        screen_h = self.mgr.gm.dpg_get_viewport_client_height()

        dpg_geom = abs_geom.to_dpg(screen_h)  # DPGGeom(x, y, w, h)

        # ------------------------------------------------------------
        # Push geometry to DPG
        # ------------------------------------------------------------
        self.mgr.gm.enqueue_dpg(
            op=DPGOp.CONFIGURE_ITEM,
            args=(info.container_id,),
            kwargs=dict(
                pos=(dpg_geom.x, dpg_geom.y),
                width=dpg_geom.width,
                height=dpg_geom.height,
            ),
        )

    def _apply_visibility(self, wid: XPWidgetID) -> None:
        """
        Queue visibility updates for this widget.

        Visibility is write-only and does not require layout readiness.
        """

        info = self.mgr.require_info(wid)

        # ------------------------------------------------------------
        # XP-AUTHENTIC VISIBILITY: inherited from all ancestors
        # ------------------------------------------------------------
        visible = info.visible
        parent = info.parent

        while visible and parent is not None:
            pinfo = self.mgr.require_info(parent)
            if not pinfo.visible:
                visible = False
                break
            parent = pinfo.parent

        # ------------------------------------------------------------
        # ROOT WIDGET → apply visibility to the DPG window
        # ------------------------------------------------------------
        if info.window.widget_root == wid:
            if info.dpg_id is not None:
                self.mgr.gm.enqueue_dpg(
                    op=DPGOp.SHOW_ITEM if visible else DPGOp.HIDE_ITEM,
                    args=(info.dpg_id,),
                )
            return

        # ------------------------------------------------------------
        # NON-ROOT WIDGET → apply visibility to its container
        # ------------------------------------------------------------
        if info.container_id is not None:
            self.mgr.gm.enqueue_dpg(
                op=DPGOp.SHOW_ITEM if visible else DPGOp.HIDE_ITEM,
                args=(info.container_id,),
            )

    def _apply_descriptor(self, wid: XPWidgetID) -> None:
        info = self.mgr.require_info(wid)

        # If not realized yet, nothing to apply
        if info.dpg_id is None:
            return

        text = info.descriptor
        wclass = info.widget_class
        xp = self.mgr.fake_xp

        # ------------------------------------------------------------
        # Caption → DPG text
        # ------------------------------------------------------------
        if wclass == xp.WidgetClass_Caption:
            self.mgr.gm.enqueue_dpg(
                op=DPGOp.CONFIGURE_ITEM,
                args=(info.dpg_id,),
                kwargs=dict(default_value=text),
            )
            return

        # ------------------------------------------------------------
        # TextField (output) → DPG text
        # ------------------------------------------------------------
        if wclass == xp.WidgetClass_TextField and not info.callbacks:
            self.mgr.gm.enqueue_dpg(
                op=DPGOp.CONFIGURE_ITEM,
                args=(info.dpg_id,),
                kwargs=dict(default_value=text),
            )
            return

        # ------------------------------------------------------------
        # TextField (editable) → DPG input value
        # ------------------------------------------------------------
        if wclass == xp.WidgetClass_TextField:
            self.mgr.gm.enqueue_dpg(
                op=DPGOp.SET_VALUE,
                args=(info.dpg_id,),
                kwargs=dict(value=text),
            )
            return

        # ------------------------------------------------------------
        # Button → label
        # ------------------------------------------------------------
        if wclass == xp.WidgetClass_Button:
            self.mgr.gm.enqueue_dpg(
                op=DPGOp.CONFIGURE_ITEM,
                args=(info.dpg_id,),
                kwargs=dict(label=text),
            )
            return

    def _apply_properties(self, wid: XPWidgetID) -> None:
        info = self.mgr.require_info(wid)
        props = info.properties
        xp = self.mgr.fake_xp
        wclass = info.widget_class

        # ------------------------------------------------------------
        # MAIN WINDOW PROPERTIES
        # ------------------------------------------------------------
        if wclass == xp.WidgetClass_MainWindow:
            # Toggle visibility of the XP-authentic close box widget
            if xp.Property_MainWindowHasCloseBoxes in props:
                close_wid = info.window._close_widget
                close_info = self.mgr.require_info(close_wid)
                close_info.set_visible(bool(props[xp.Property_MainWindowHasCloseBoxes]))
            return

        # ------------------------------------------------------------
        # SCROLLBAR PROPERTIES
        # ------------------------------------------------------------
        if wclass == xp.WidgetClass_ScrollBar:
            dpg_id = info.dpg_id
            if dpg_id is None:
                return

            # Min
            if xp.Property_ScrollBarMin in props:
                self.mgr.gm.enqueue_dpg(
                    op=DPGOp.CONFIGURE_ITEM,
                    args=(dpg_id,),
                    kwargs=dict(min_value=int(props[xp.Property_ScrollBarMin])),
                )

            # Max
            if xp.Property_ScrollBarMax in props:
                self.mgr.gm.enqueue_dpg(
                    op=DPGOp.CONFIGURE_ITEM,
                    args=(dpg_id,),
                    kwargs=dict(max_value=int(props[xp.Property_ScrollBarMax])),
                )

            # Slider position
            if xp.Property_ScrollBarSliderPosition in props:
                self.mgr.gm.enqueue_dpg(
                    op=DPGOp.SET_VALUE,
                    args=(dpg_id,),
                    kwargs=dict(value=int(props[xp.Property_ScrollBarSliderPosition])),
                )

            return
