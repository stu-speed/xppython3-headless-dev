# window.py
from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import DPGOp, WindowExInfo, XPGeom, XPPoint
from simless.libs.graphics import GraphicsManager
from xp_typing import (
    XPLMWindowDecoration, XPLMWindowID, XPLMWindowLayer
)

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class WindowManager:
    """Owns WindowEx registry, IDs, and Z-order."""

    BORDER_TOP = 4
    BORDER_LEFT = 4
    BORDER_RIGHT = 4
    BORDER_BOTTOM = 4
    TITLE_BAR_HEIGHT = 18 + BORDER_TOP

    def __init__(self, fake_xp: FakeXP) -> None:
        self._windows_ex: OrderedDict[XPLMWindowID | int, WindowExInfo] = OrderedDict()
        self._next_window_id: int = 1
        self.fake_xp = fake_xp

    @property
    def gm(self) -> GraphicsManager:
        return self.fake_xp.graphics_manager

    # ------------------------------------------------------------
    # DIRTY HELPERS
    # ------------------------------------------------------------

    def any_dirty_xp_to_dpg(self) -> bool:
        return any(win._dirty_xp_to_dpg for win in self.all_info())

    def clear_dirty_xp_to_dpg(self) -> None:
        for win in self.all_info():
            win._dirty_xp_to_dpg = False

    def any_dirty_dpg_to_xp(self) -> bool:
        return any(win._dirty_dpg_to_xp for win in self.all_info())

    def clear_dirty_dpg_to_xp(self) -> None:
        for win in self.all_info():
            win._dirty_dpg_to_xp = False

    def create_window(
        self,
        *,
        left: int,
        top: int,
        right: int,
        bottom: int,
        visible: bool,
        decoration: XPLMWindowDecoration,
        layer: XPLMWindowLayer,
        draw_cb=None,
        click_cb=None,
        right_click_cb=None,
        key_cb=None,
        cursor_cb=None,
        wheel_cb=None,
        refcon=None,
        no_title_bar: bool = False,
    ) -> WindowExInfo:

        wid = XPLMWindowID(self._next_window_id)
        self._next_window_id += 1

        # ---------------------------------------------------------
        # FRAME = input rectangle (always)
        # ---------------------------------------------------------
        frame = XPGeom(left, top, right, bottom)

        # ---------------------------------------------------------
        # CLIENT AREA (hit-test area)
        # ---------------------------------------------------------
        title_offset = self.BORDER_TOP if no_title_bar else self.TITLE_BAR_HEIGHT
        client = XPGeom(
            left=frame.left + self.BORDER_LEFT,
            top=frame.top - title_offset,
            right=frame.right - self.BORDER_RIGHT,
            bottom=frame.bottom + self.BORDER_BOTTOM,
        )

        # ---------------------------------------------------------
        # Create WindowExInfo
        # ---------------------------------------------------------
        info = WindowExInfo(
            wid=wid,
            _frame=frame,
            _client=client,
            _visible=visible,
            _decoration=decoration,
            _layer=layer,
            draw_cb=draw_cb,
            click_cb=click_cb,
            right_click_cb=right_click_cb,
            key_cb=key_cb,
            cursor_cb=cursor_cb,
            wheel_cb=wheel_cb,
            refcon=refcon,
            _dpg_window_id=f"xplm_window_{wid}",
            _drawlist_id=f"xplm_window_drawlist_{wid}",
        )

        # Insert at end = top of Z-order
        self._windows_ex[wid] = info

        # ---------------------------------------------------------
        # Backend creation (DPG)
        # ---------------------------------------------------------
        dpg_geom = info.frame.to_dpg(self.gm.dpg_get_viewport_client_height())

        self.gm.enqueue_dpg(
            DPGOp.ADD_WINDOW,
            args=(),
            kwargs=dict(
                tag=info.dpg_tag,
                pos=(dpg_geom.x, dpg_geom.y),
                width=dpg_geom.width,
                height=dpg_geom.height,
                no_title_bar=no_title_bar,
                no_resize=False,
                no_move=False,
                no_scrollbar=True,
                no_collapse=True,
                show=info.visible,
            ),
        )

        self.gm.enqueue_dpg(
            DPGOp.ADD_DRAWLIST,
            args=(),
            kwargs=dict(
                tag=info.drawlist_tag,
                width=dpg_geom.width,
                height=dpg_geom.height,
                parent=info.dpg_tag,
            ),
        )

        return info

    def destroy_window(self, wid: XPLMWindowID) -> None:
        """
        Destroy a WindowEx window.

        XP‑authentic behavior:
        - Destroy the DPG window (auto‑deletes all child DPG items)
        - Destroy all widgets belonging to this WindowEx
        - Remove the WindowEx from the registry
        - Clear active drawlist if needed
        - Mark graphics as needing redraw
        """

        info = self.get_info(wid)
        if info is None:
            # XP tolerates destroying an already‑destroyed window
            return

        removed = self._windows_ex.pop(wid, None)
        if removed is None:
            return

        if self.fake_xp.graphics_manager.get_active_drawlist() == removed.drawlist_tag:
            self.fake_xp.graphics_manager.set_active_drawlist(self.fake_xp.graphics_manager._screen_drawlist_back)

    # ------------------------------------------------------------
    # WINDOW LOOKUP / Z-ORDER
    # ------------------------------------------------------------

    def get_info(self, wid: int | XPLMWindowID) -> Optional[WindowExInfo]:
        return self._windows_ex.get(wid)

    def require_info(self, wid: XPLMWindowID) -> WindowExInfo:
        info = self._windows_ex.get(wid)
        if info is None:
            raise RuntimeError(f"Invalid window ID: {wid}")
        return info

    def all_info(self) -> List[WindowExInfo]:
        windows: List[WindowExInfo] = list(self._windows_ex.values())
        return sorted(windows, key=lambda w: w.layer)

    def require_info_by_dpg_id(self, dpg_id: str) -> WindowExInfo:
        """
        Reverse lookup: find the WindowExInfo whose DPG window tag matches dpg_id.
        """
        for info in self._windows_ex.values():
            if info.dpg_tag == dpg_id:
                return info
        raise RuntimeError(f"No WindowExInfo found for DPG window: {dpg_id}")

    def bring_to_front(self, info: WindowExInfo):
        """
        Reinsert to ordered dict
        """
        wid = info.wid
        data = self._windows_ex.pop(wid)
        self._windows_ex[wid] = data

    def hit_test(self, pt: XPPoint) -> WindowExInfo | None:
        """
        Return the topmost visible window whose frame contains the XP coordinate.
        Uses the XPGeom returned by info.frame.
        """
        for win in reversed(self.all_info()):  # topmost → bottommost
            if not win.visible:
                continue
            if win.frame.contains(pt):
                return win
        return None

    def iter_top_to_bottom(self):
        """
        Topmost-first ordering.
        Since wid is stable identity (not Z-order), we rely on registry order.
        Highest layer first, then insertion order within that layer.
        """
        # Group by layer, preserve insertion order within each layer
        layers = sorted(
            set(info.layer for info in self.fake_xp.window_manager.all_info()),
            reverse=True,
        )

        for layer in layers:
            # Yield windows in this layer in insertion order (topmost last)
            for info in reversed(
                [
                    w for w in self.fake_xp.window_manager.all_info()
                    if w.layer == layer
                ]
            ):
                yield info
