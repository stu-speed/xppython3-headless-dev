# _graphics.py
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable, List, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import WindowExInfo, XPGeom
from XPPython3.xp_typing import (
    XPLMCursorStatus, XPLMMouseStatus, XPLMWindowDecoration, XPLMWindowID, XPLMWindowLayer
)

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class WindowManager:
    """Owns WindowEx registry, IDs, and Z-order."""

    def __init__(self, fake_xp: FakeXP) -> None:
        self._windows_ex: OrderedDict[XPLMWindowID, WindowExInfo] = OrderedDict()
        self._next_window_id: int = 1
        self.fake_xp = fake_xp

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

    # ------------------------------------------------------------
    # WINDOW REGISTRATION
    # ------------------------------------------------------------

    def register_windowex(
        self,
        *,
        left: int,
        top: int,
        right: int,
        bottom: int,
        visible: bool,
        decoration: XPLMWindowDecoration,
        layer: XPLMWindowLayer,
        draw_cb: Optional[Callable[[XPLMWindowID, Any], None]],
        click_cb: Optional[
            Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
        ],
        right_click_cb: Optional[
            Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
        ],
        key_cb: Optional[
            Callable[[XPLMWindowID, int, int, int, Any, int], int]
        ],
        cursor_cb: Optional[
            Callable[[XPLMWindowID, int, int, Any], XPLMCursorStatus]
        ],
        wheel_cb: Optional[
            Callable[[XPLMWindowID, int, int, int, int, Any], int]
        ],
        refcon: Any,
    ) -> WindowExInfo:

        wid = XPLMWindowID(self._next_window_id)
        self._next_window_id += 1

        xp_geom = XPGeom(left, top, right, bottom)

        info = WindowExInfo(
            wid=wid,
            _frame=xp_geom,
            _client=xp_geom,
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
            self.fake_xp.graphics_manager.set_active_drawlist(None)

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

    def bring_to_front(self, info: WindowExInfo):
        """
        Reinsert to ordered dict
        """
        wid = info.wid
        data = self._windows_ex.pop(wid)
        self._windows_ex[wid] = data

    def hit_test(self, xp_x: int, xp_y: int) -> WindowExInfo | None:
        """
        Return the topmost visible window whose frame contains the XP coordinate.
        Uses the XPGeom returned by info.frame.
        """
        for win in reversed(self.all_info()):  # topmost → bottommost
            if not win.visible:
                continue
            if win.frame.contains(xp_x, xp_y):
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
