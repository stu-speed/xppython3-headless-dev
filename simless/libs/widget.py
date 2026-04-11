# widget_manager.py

from __future__ import annotations

from typing import Dict, Iterable, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import DPGGeom, DPGOp, WGeom, WidgetInfo, WindowExInfo
from XPPython3.xp_typing import XPWidgetClass, XPWidgetID

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class WidgetManager:
    """
    Global XPWidget registry + XP→DPG sync engine.

    Responsibilities:
      - Allocate XPWidgetIDs
      - Own the global WidgetInfo registry
      - Maintain parent/child relationships
      - Structural realization (ensure_dpg)
      - XP→DPG sync (geometry + visibility)
      - Draw callback dispatch
      - Widget destruction
      - Window‑scoped iteration
      - Z‑order mutation (per-window)
      - Focus mutation (per-window)
      - Hit-testing
    """

    def __init__(self, fake_xp: FakeXP) -> None:
        self._widgets: Dict[XPWidgetID, WidgetInfo] = {}
        self._next_widget_id: int = 1
        self.fake_xp = fake_xp
        self.gm = fake_xp.graphics_manager

    def allocate_widget_id(self) -> XPWidgetID:
        wid = XPWidgetID(self._next_widget_id)
        self._next_widget_id += 1
        return wid

    def get_widget(self, wid: XPWidgetID) -> Optional[WidgetInfo]:
        return self._widgets.get(wid)

    def require_info(self, wid: XPWidgetID) -> WidgetInfo:
        info = self._widgets.get(wid)
        if info is None:
            raise KeyError(f"Widget {wid} does not exist")
        return info

    def create_widget(
        self,
        *,
        widget_class: XPWidgetClass,
        window: WindowExInfo,
        geometry: WGeom,
        parent: Optional[XPWidgetID] = None,
        descriptor: str = "",
        visible: bool = True,
    ) -> WidgetInfo:

        wid = self.allocate_widget_id()

        info = WidgetInfo(
            wid=wid,
            widget_class=widget_class,
            window=window,
            _geometry=geometry,  # ← FIXED: use property, not _geometry
            parent=parent,
            _descriptor=descriptor,
            _visible=visible,
        )

        self._widgets[wid] = info

        # Attach to parent
        if parent is not None:
            pinfo = self.require_info(parent)
            pinfo.add_child(wid)  # dirties window internally

        # If window has no root, this becomes root
        if window.widget_root is None:
            window.set_widget_root(wid)

        # Add to z-order (dirties window internally)
        window.add_to_z_order(wid)

        return info

    # ------------------------------------------------------------
    # DESTRUCTION
    # ------------------------------------------------------------

    def destroy_widget(self, wid: XPWidgetID) -> None:
        """
        Destroy a widget and its subtree.
        Structural only: DPG deletions are queued.
        """
        info = self.get_widget(wid)
        if info is None:
            return

        window = info.window

        # Recursively destroy children
        for child_id in list(info.children):
            self.destroy_widget(child_id)

        # Queue DPG deletions
        if info.dpg_id is not None:
            self.gm.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.dpg_id,))
        if info.container_id is not None and info.container_id != info.dpg_id:
            self.gm.enqueue_dpg(DPGOp.DELETE_ITEM, args=(info.container_id,))

        # Detach from parent
        if info.parent is not None:
            pinfo = self.require_info(info.parent)
            pinfo.remove_child(wid)  # dirties window internally

        # Clear window root if needed
        if window.widget_root == wid:
            window.set_widget_root(None)

        # Remove from z-order (dirties window internally)
        window.remove_from_z_order(wid)

        # Clear focus if needed (dirties window internally)
        if window.focused_widget == wid:
            window.clear_widget_focus()

        # Remove from registry
        self._widgets.pop(wid, None)

    def kill_all_widgets_in_window(self, window: WindowExInfo) -> None:
        root = window.widget_root
        if root is None:
            return

        self.destroy_widget(root)

        # Root already cleared by destroy_widget if needed
        window.clear_widget_focus()  # dirties window internally
        window._z_order.clear()  # direct clear is fine
        window._dirty_xp_to_dpg = True  # ensure sync after mass deletion

    def raise_widget(self, wid: XPWidgetID) -> None:
        info = self.require_info(wid)
        info.window.raise_widget(wid)  # dirties window internally

    def lower_widget(self, wid: XPWidgetID) -> None:
        info = self.require_info(wid)
        info.window.lower_widget(wid)  # dirties window internally

    def set_focus(self, wid: Optional[XPWidgetID]) -> None:
        if wid is None:
            return
        info = self.require_info(wid)
        info.window.set_focused_widget(wid)
        info.window._dirty_xp_to_dpg = True

    def clear_focus(self, window: WindowExInfo) -> None:
        window.clear_widget_focus()
        window._dirty_xp_to_dpg = True

    def get_focused_widget(self, window: WindowExInfo) -> Optional[XPWidgetID]:
        return window.focused_widget

    def hit_test(self, window: WindowExInfo, x: int, y: int) -> Optional[XPWidgetID]:
        """
        Return the topmost widget at (x, y) in window coordinates.
        """
        for wid in reversed(window.z_order):
            info = self.get_widget(wid)
            if info and info.geometry.contains(x, y):
                return wid
        return None

    def iter_subtree(self, root: XPWidgetID) -> Iterable[WidgetInfo]:
        stack = [root]
        while stack:
            wid = stack.pop()
            info = self.get_widget(wid)
            if info is None:
                continue
            yield info
            stack.extend(reversed(info.children))

    def iter_window_widgets(self, window: WindowExInfo) -> Iterable[WidgetInfo]:
        root = window.widget_root
        if root is None:
            return ()
        return self.iter_subtree(root)

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
        for win in self.fake_xp.window_manager.all_info():
            if win._dirty_widgets:
                self._render_widgets(win)
                win._dirty_widgets = False

        # ------------------------------------------------------------
        # 2. Dispatch draw callbacks (always)
        # ------------------------------------------------------------
        for win in self.fake_xp.window_manager.all_info():
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

        info = self.require_info(wid)

        # Only root widgets should receive draw callbacks
        if info.window.widget_root != wid:
            return

        for cb in info.callbacks:
            cb(self.fake_xp.Msg_Draw, wid, wid, None)

    def _render_widgets(self, win):
        for info in self.iter_window_widgets(win):
            wid = info.wid

            # 1. Ensure DPG structure exists
            self._ensure_dpg_item_for_widget(wid)

            # 2. Geometry
            self._apply_geometry_if_needed(wid)

            # 3. Visibility
            self._apply_visibility(wid)

            # 4. Descriptor text
            self._apply_descriptor_if_needed(wid)

            # 5. Widget properties (scrollbar min/max/value, etc.)
            self._apply_properties(wid)

    def _ensure_dpg_item_for_widget(self, wid: XPWidgetID) -> None:
        """
        Ensure that a DearPyGui representation exists for the given XPWidget.
        Structural only: queue backend ops, do not execute immediately.
        """

        info = self.require_info(wid)

        # Already realized?
        if info.dpg_id is not None and info.container_id is not None:
            return

        wclass = info.widget_class
        desc = info.descriptor or ""

        # Deterministic DPG IDs
        dpg_id = f"xp_widget_{wid}"
        container_id = f"xp_widget_container_{wid}"

        # ============================================================
        # ROOT WIDGETS → create top-level DPG window
        # ============================================================
        if wclass in (
                self.fake_xp.WidgetClass_MainWindow,
                self.fake_xp.WidgetClass_SubWindow,
        ):
            win = info.window  # WindowExInfo

            # Create the DPG window only once, keyed off the widget's dpg_id
            if info.dpg_id is None:
                win._dpg_window_id = dpg_id  # bind window to this tag

                self.gm.enqueue_dpg(
                    op=DPGOp.ADD_WINDOW,
                    kwargs=dict(
                        tag=dpg_id,
                        label=desc or "Window",
                        width=max(1, info.geometry.width),
                        height=max(1, info.geometry.height),
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

        # ============================================================
        # NON-ROOT WIDGETS → child_window + control
        # ============================================================
        parent_wid = info.parent
        if parent_wid is None:
            raise RuntimeError(f"[Create] wid={wid} ERROR: control has no parent")

        # Ensure parent is realized first
        self._ensure_dpg_item_for_widget(parent_wid)

        parent_info = self.require_info(parent_wid)
        parent_container = parent_info.container_id
        if parent_container is None:
            raise RuntimeError(f"[Create] wid={wid} ERROR: parent container missing")

        # ------------------------------------------------------------
        # Create container (child_window)
        # ------------------------------------------------------------
        if info.container_id is None:
            info.container_id = container_id

            self.gm.enqueue_dpg(
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
            info.container_geom_applied = None

        # ------------------------------------------------------------
        # Create actual control
        # ------------------------------------------------------------
        if info.dpg_id is None:
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
                    w = self.require_info(widget_id)
                    w.edit_buffer = app_data
                    self.fake_xp.sendMessageToWidget(
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
                min_v = info.properties.get(self.fake_xp.Property_ScrollBarMin, 0)
                max_v = info.properties.get(self.fake_xp.Property_ScrollBarMax, 100)
                cur_v = info.properties.get(
                    self.fake_xp.Property_ScrollBarSliderPosition, min_v
                )

                def _on_scroll(sender, app_data, user_data):
                    widget_id = XPWidgetID(user_data)
                    new_pos = int(app_data)
                    self.fake_xp.setWidgetProperty(
                        widget_id,
                        self.fake_xp.Property_ScrollBarSliderPosition,
                        new_pos,
                    )
                    self.fake_xp.sendMessageToWidget(
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
                    self.fake_xp.sendMessageToWidget(
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

    def _apply_geometry_if_needed(self, wid: XPWidgetID) -> None:
        """
        Apply XP → DPG geometry for this widget if needed.

        Preconditions:
          - Widget must already be structurally realized (container_id or dpg_id exists)
          - XP geometry is authoritative and already updated
        """

        info = self.require_info(wid)

        # Nothing to apply until DPG objects exist
        if info.container_id is None and info.dpg_id is None:
            return

        # XP geometry (WGeom object, top-origin)
        g = info.geometry
        left = g.left
        top = g.top
        right = g.right
        bottom = g.bottom

        width = right - left
        height = top - bottom

        # ============================================================
        # ROOT WIDGETS → configure the DPG window
        # ============================================================
        if info.window.widget_root == wid:

            if info.dpg_id is None:
                raise RuntimeError(
                    f"_apply_geometry_if_needed: root widget wid={wid} has no dpg_id"
                )

            # Convert XP top-origin → DPG bottom-origin
            dpg_x = left
            dpg_y = top - height

            desired = DPGGeom(dpg_x, dpg_y, width, height)

            if info.container_geom_applied != desired:
                self.gm.enqueue_dpg(
                    op=DPGOp.CONFIGURE_ITEM,
                    args=(info.dpg_id,),
                    kwargs=dict(
                        pos=(dpg_x, dpg_y),
                        width=width,
                        height=height,
                    ),
                )
                info.container_geom_applied = desired

            return

        # ============================================================
        # CONTROLS → configure their child_window container
        # ============================================================
        parent_info = self.require_info(info.parent)
        pg = parent_info.geometry

        # XP local coordinates (parent-relative)
        lx = left - pg.left
        ly = pg.top - top

        desired = DPGGeom(lx, ly, width, height)

        if info.container_geom_applied != desired:
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
        """

        info = self.require_info(wid)

        # If not created yet, nothing to show/hide
        if info.container_id is None:
            return

        # ------------------------------------------------------------
        # XP-AUTHENTIC VISIBILITY: inherited from all ancestors
        # ------------------------------------------------------------
        visible = info.visible
        parent = info.parent

        while visible and parent is not None:
            pinfo = self.require_info(parent)
            if not pinfo.visible:
                visible = False
                break
            parent = pinfo.parent

        # ------------------------------------------------------------
        # Apply visibility to the container (child_window or root window)
        # ------------------------------------------------------------
        self.gm.enqueue_dpg(
            op=DPGOp.SHOW_ITEM if visible else DPGOp.HIDE_ITEM,
            args=(info.container_id,),
        )

        # ------------------------------------------------------------
        # Root widgets also apply visibility to the DPG window itself
        # ------------------------------------------------------------
        if info.window.widget_root == wid and info.dpg_id is not None:
            self.gm.enqueue_dpg(
                op=DPGOp.SHOW_ITEM if visible else DPGOp.HIDE_ITEM,
                args=(info.dpg_id,),
            )

    def _apply_descriptor_if_needed(self, wid: XPWidgetID) -> None:
        info = self.require_info(wid)

        # If not realized yet, nothing to apply
        if info.dpg_id is None:
            return

        # Only update if descriptor changed
        if info.descriptor == info._last_descriptor:
            return

        text = info.descriptor
        wclass = info.widget_class

        # Caption → DPG text
        if wclass == self.fake_xp.WidgetClass_Caption:
            self.gm.enqueue_dpg(
                op=DPGOp.CONFIGURE_ITEM,
                args=(info.dpg_id,),
                kwargs=dict(default_value=text),
            )

        # TextField → input text
        elif wclass == self.fake_xp.WidgetClass_TextField:
            self.gm.enqueue_dpg(
                op=DPGOp.SET_VALUE,
                args=(info.dpg_id,),
                kwargs=dict(value=text),
            )

        # Button → label
        elif wclass == self.fake_xp.WidgetClass_Button:
            self.gm.enqueue_dpg(
                op=DPGOp.CONFIGURE_ITEM,
                args=(info.dpg_id,),
                kwargs=dict(label=text),
            )

        # Unhandled widget class
        else:
            self.fake_xp.log(f"unhandled setdescriptor class: {wclass}")

        # Cache applied descriptor
        info._last_descriptor = info.descriptor

    def _apply_properties(self, wid: XPWidgetID) -> None:
        info = self.require_info(wid)
        props = info.properties
        wclass = info.widget_class

        # ScrollBar → update DPG slider
        if wclass == self.fake_xp.WidgetClass_ScrollBar:

            if self.fake_xp.Property_ScrollBarMin in props:
                self.gm.enqueue_dpg(
                    op=DPGOp.CONFIGURE_ITEM,
                    args=(info.dpg_id,),
                    kwargs=dict(min_value=int(props[self.fake_xp.Property_ScrollBarMin])),
                )

            if self.fake_xp.Property_ScrollBarMax in props:
                self.gm.enqueue_dpg(
                    op=DPGOp.CONFIGURE_ITEM,
                    args=(info.dpg_id,),
                    kwargs=dict(max_value=int(props[self.fake_xp.Property_ScrollBarMax])),
                )

            if self.fake_xp.Property_ScrollBarSliderPosition in props:
                self.gm.enqueue_dpg(
                    op=DPGOp.SET_VALUE,
                    args=(info.dpg_id,),
                    kwargs=dict(value=int(props[self.fake_xp.Property_ScrollBarSliderPosition])),
                )

            return
