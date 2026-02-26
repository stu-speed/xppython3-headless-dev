# simless/libs/fake_xp_dataref_viewer.py
# ===========================================================================
# FakeXPDataRefViewer — widget-based inspector for all FakeDataRefs
# ===========================================================================

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Pattern

from XPPython3 import xp
from XPPython3.xp_typing import XPWidgetID, XPWidgetMessage

from simless.libs.fake_xp_interface import FakeXPInterface
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
    def __init__(self, xp_: FakeXPInterface) -> None:
        self.xp = xp_

        self.win: XPWidgetID | None = None
        self.status_caption: XPWidgetID | None = None

        self.filter_label: XPWidgetID | None = None
        self.filter_field: XPWidgetID | None = None
        self.filter_button: XPWidgetID | None = None

        self.data_caption: XPWidgetID | None = None

        self.state = ViewerState()
        self._next_idx: int = 1
        self._dirty: bool = False

        self._filter_text: str = ""
        self._filter_regex: Optional[Pattern[str]] = None

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

        # STATUS
        self.status_caption = xp.createWidget(
            110, 770, 850, 735,
            1, "", 0, self.win, xp.WidgetClass_Caption
        )

        # FILTER (single line)
        y_top = 720
        y_bot = 700

        self.filter_label = xp.createWidget(
            110, y_top, 260, y_bot,
            1, "FILTER (regex):", 0, self.win, xp.WidgetClass_Caption
        )

        self.filter_field = xp.createWidget(
            270, y_top, 650, y_bot,
            1, "", 0, self.win, xp.WidgetClass_TextField
        )
        xp.setWidgetProperty(
            self.filter_field,
            xp.Property_TextFieldType,
            xp.TextEntryField,
        )

        self.filter_button = xp.createWidget(
            660, y_top, 740, y_bot,
            1, "Apply", 0, self.win, xp.WidgetClass_Button
        )

        # DATAREF LIST
        self.data_caption = xp.createWidget(
            110, 685, 850, 250,
            1, "", 0, self.win, xp.WidgetClass_Caption
        )

        # Callbacks
        xp.addWidgetCallback(self.win, self._widget_handler)
        xp.addWidgetCallback(self.filter_field, self._widget_handler)
        xp.addWidgetCallback(self.filter_button, self._widget_handler)

        self._dirty = True

    def close(self) -> None:
        if self.win:
            xp.destroyWidget(self.win, 1)
            self.win = None

    # --------------------------------------------------------

    def _widget_handler(
        self,
        msg: XPWidgetMessage,
        widget: XPWidgetID,
        p1: Any,
        p2: Any,
    ) -> int:
        if msg == xp.Message_CloseButtonPushed and widget == self.win:
            xp.hideWidget(self.win)
            return 1

        # TextField commits are event-driven
        if msg == xp.Msg_TextFieldChanged and widget == self.filter_field:
            self._filter_text = str(p1)
            return 1

        # Button presses are delivered to the parent window
        if msg == xp.Msg_PushButtonPressed and widget == self.filter_button:
            self._apply_filter(self._filter_text)
            return 1

        return 0

    # --------------------------------------------------------

    def refresh(self) -> None:
        if not self._dirty or not self.win:
            self._dirty = False
            return

        self._render_status()
        self._render_datarefs()
        self._dirty = False

    # --------------------------------------------------------

    def _render_status(self) -> None:
        runner = self.xp.simless_runner
        enabled, connected, last_error = runner.bridge_status

        if not enabled:
            text = "STATUS\nBridge: DISABLED"
        elif connected:
            text = "STATUS\nBridge: CONNECTED"
        else:
            reason = f"\nReason: {last_error}" if last_error else ""
            text = f"STATUS\nBridge: DISCONNECTED{reason}"

        xp.setWidgetDescriptor(self.status_caption, text)

    def _render_datarefs(self) -> None:
        lines: list[str] = []
        lines.append("  D  IDX  NAME                                               W  VALUE")
        lines.append("  -- ---- -------------------------------------------------- -  -----")

        for ref in sorted(self.state.refs.values(), key=lambda r: r.meta.idx):
            meta = ref.meta

            if self._filter_regex and not self._filter_regex.search(meta.name):
                continue

            mark = "*" if ref.changed else " "
            dummy = "D" if meta.is_dummy else " "
            lines.append(
                f"{mark}{dummy} {meta.idx:4d}  {meta.name:50s}  "
                f"{'W' if meta.writable else '-'}  {ref.value}"
            )

        xp.setWidgetDescriptor(self.data_caption, "\n".join(lines))

    def _apply_filter(self, text: str) -> None:
        text = (text or "").strip()

        if not text:
            self._filter_regex = None
        else:
            self._filter_regex = re.compile(re.escape(text))

        self._dirty = True


# ============================================================
# Viewer client (runner-owned)
# ============================================================

class FakeXPDataRefViewerClient:
    def __init__(self, xp_: FakeXPInterface):
        self.xp = xp_
        self.viewer = DataRefViewer(xp_)
        self._attached = False

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True

        for ref in self.xp.all_handles():
            self._add_ref(ref)

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

    def poll(self) -> None:
        for state in self.viewer.state.refs.values():
            self._update_value(state)
        self.viewer.refresh()

    def _on_new_handle(self, ref: FakeDataRef) -> None:
        self._add_ref(ref)

    def _add_ref(self, ref: FakeDataRef) -> None:
        if ref.path in self.viewer.state.refs:
            return

        info = self.xp.getDataRefInfo(ref)
        value = self._read_value(ref, info)

        meta = RefMeta(
            idx=self.viewer._next_idx,
            name=ref.path,
            type=info.type,
            writable=info.writable,
            array_size=getattr(info, "size", 0),
            is_dummy=getattr(ref, "is_dummy", False),
        )

        self.viewer.state.refs[ref.path] = RefState(
            meta=meta,
            value=value,
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
