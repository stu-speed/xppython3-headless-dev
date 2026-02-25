# simless/libs/fake_xp_dataref_viewer.py
# ===========================================================================
# FakeXPDataRefViewer — widget-based inspector for all FakeDataRefs
#
# PURPOSE
#   Inspect *all* FakeDataRefs that exist in FakeXP.
#
# DISCOVERY MODEL
#   • Initial snapshot via FakeXP helpers
#   • Incremental discovery via handle callback
#   • NO discovery during poll()
#
# INVARIANTS
#   • Viewer reflects reality, not intent
#   • No DataRefManager dependency
#   • No bridge coupling
#   • Read-only
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable

from XPPython3 import xp
from XPPython3.xp_typing import XPWidgetID, XPWidgetMessage

from simless.libs.fake_xp import FakeXP
from simless.libs.fake_xp_dataref_types import DRefType, FakeDataRef

LOG_PREFIX = "[FakeXPDataRefViewer]"


def log(msg: str) -> None:
    xp.log(f"{LOG_PREFIX} {msg}")


# ============================================================
# Viewer state model
# ============================================================

@dataclass
class RefMeta:
    idx: int
    name: str
    type: int
    writable: bool
    array_size: int
    is_dummy: bool


@dataclass
class RefState:
    meta: RefMeta
    value: Any = None
    last_value: Any = None
    changed: bool = False


class ViewerState:
    def __init__(self) -> None:
        self.refs: Dict[str, RefState] = {}


# ============================================================
# Widget-only viewer
# ============================================================

class DataRefViewer:
    def __init__(self) -> None:
        self.win: XPWidgetID | None = None
        self.caption_list: XPWidgetID | None = None
        self.state = ViewerState()

        self._handler: Optional[Callable] = None
        self._dirty: bool = False
        self._next_idx: int = 1

        log("Viewer initialized")

    # --------------------------------------------------------

    def open(self) -> None:
        if self.win:
            return

        self.win = xp.createWidget(
            100, 800, 900, 200,
            1,
            "FakeXP DataRef Viewer",
            1,
            0,
            xp.WidgetClass_MainWindow,
        )
        xp.setWidgetProperty(self.win, xp.Property_MainWindowHasCloseBoxes, 1)

        self.caption_list = xp.createWidget(
            110, 770, 850, 250,
            1,
            "",
            0,
            self.win,
            xp.WidgetClass_Caption,
        )

        def handler(msg: XPWidgetMessage, widget: XPWidgetID, p1: Any, p2: Any) -> int:
            return self._widget_handler(msg, widget, p1, p2)

        self._handler = handler
        xp.addWidgetCallback(self.win, handler)

    def close(self) -> None:
        if self.win:
            xp.destroyWidget(self.win, 1)
            self.win = None
            self.caption_list = None
            self._handler = None

    # --------------------------------------------------------

    def _widget_handler(
        self,
        msg: XPWidgetMessage,
        widget: XPWidgetID,
        p1: Any,
        p2: Any,
    ) -> int:
        if widget != self.win:
            return 0

        if msg == xp.Message_CloseButtonPushed:
            xp.hideWidget(self.win)
            return 1

        return 0

    # --------------------------------------------------------

    def refresh(self) -> None:
        if not self._dirty or not self.win or not self.caption_list:
            self._dirty = False
            return

        lines: list[str] = []
        refs_sorted = sorted(self.state.refs.values(), key=lambda r: r.meta.idx)

        for ref in refs_sorted:
            meta = ref.meta
            mark = "*" if ref.changed else " "
            dummy = "D" if meta.is_dummy else " "
            lines.append(
                f"{mark}{dummy} {meta.idx:3d}  {meta.name:50s}  "
                f"{'W' if meta.writable else '-'}  {ref.value}"
            )

        xp.setWidgetDescriptor(self.caption_list, "\n".join(lines))
        self._dirty = False


# ============================================================
# FakeXP viewer client (runner-owned)
# ============================================================

class FakeXPDataRefViewerClient:
    def __init__(self, xp: FakeXP):
        self.xp = xp
        self.viewer = DataRefViewer()
        self._attached = False

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True

        # Initial snapshot ONLY
        for ref in self.xp.all_handles():
            self._add_ref(ref)

        # Subscribe to future handles
        self.xp.attach_handle_callback(self._on_new_handle)

        self.viewer.open()
        log("Viewer attached")

    def detach(self) -> None:
        if not self._attached:
            return
        self._attached = False

        self.xp.detach_handle_callback()
        self.viewer.close()
        log("Viewer detached")

    # --------------------------------------------------------
    # Per-frame update (values only)
    # --------------------------------------------------------

    def poll(self) -> None:
        for state in self.viewer.state.refs.values():
            self._update_value(state)

        self.viewer.refresh()

    # --------------------------------------------------------
    # Handle discovery
    # --------------------------------------------------------

    def _on_new_handle(self, ref: FakeDataRef) -> None:
        self._add_ref(ref)

    # --------------------------------------------------------
    # Internal helpers
    # --------------------------------------------------------

    def _add_ref(self, ref: FakeDataRef) -> None:
        path = ref.path
        if path in self.viewer.state.refs:
            return

        info = self.xp.getDataRefInfo(ref)
        value = self._read_value(ref, info)

        meta = RefMeta(
            idx=self.viewer._next_idx,
            name=path,
            type=info.type,
            writable=info.writable,
            array_size=getattr(info, "size", 0),
            is_dummy=getattr(ref, "is_dummy", False),
        )

        self.viewer.state.refs[path] = RefState(
            meta=meta,
            value=value,
            last_value=None,
            changed=True,
        )

        self.viewer._next_idx += 1
        self.viewer._dirty = True

    def _update_value(self, state: RefState) -> None:
        ref = self.xp.get_handle(state.meta.name)
        if ref is None:
            return

        info = self.xp.getDataRefInfo(ref)
        new_value = self._read_value(ref, info)

        state.last_value = state.value
        state.value = new_value
        state.changed = (state.last_value != state.value)
        if state.changed:
            self.viewer._dirty = True

    def _read_value(self, ref: FakeDataRef, info) -> Any:
        t = info.type
        xp_ = self.xp

        if t & DRefType.FLOAT:
            return xp_.getDataf(ref)
        if t & DRefType.INT:
            return xp_.getDatai(ref)
        if t & DRefType.DOUBLE:
            return xp_.getDatad(ref)
        if t & DRefType.FLOAT_ARRAY:
            buf = [0.0] * info.size
            xp_.getDatavf(ref, buf, 0, info.size)
            return buf
        if t & DRefType.INT_ARRAY:
            buf = [0] * info.size
            xp_.getDatavi(ref, buf, 0, info.size)
            return buf
        if t & DRefType.BYTE_ARRAY:
            buf = bytearray(info.size)
            xp_.getDatab(ref, buf, 0, info.size)
            return buf

        return None
