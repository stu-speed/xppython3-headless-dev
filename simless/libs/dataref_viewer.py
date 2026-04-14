# simless/libs/fake_xp_dataref_viewer.py
# ===========================================================================
# FakeXPDataRefViewer — widget-based inspector for all FakeDataRefs
# ===========================================================================

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Pattern, TYPE_CHECKING

from simless.libs.dataref import DataRefManager
from simless.libs.fake_xp_types import FakeDataRef
from XPPython3.xp_typing import XPWidgetID, XPWidgetMessage

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


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
    LOG_PREFIX = "[FakeXPDataRefViewer]"

    def __init__(self, xp: FakeXP) -> None:
        self.fake_xp = xp

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

        self.win = self.fake_xp.createWidget(
            100, 800, 1400, 200,
            1,
            "FakeXP DataRef Viewer",
            1,
            0,
            self.fake_xp.WidgetClass_MainWindow,
        )
        self.fake_xp.setWidgetProperty(self.win, self.fake_xp.Property_MainWindowHasCloseBoxes, 1)

        # STATUS (single line)
        self.status_caption = self.fake_xp.createWidget(
            110, 770, 850, 735,
            1, "", 0, self.win, self.fake_xp.WidgetClass_Caption
        )

        # FILTER (single line, moved up)
        y_top = 745
        y_bot = 725

        self.filter_label = self.fake_xp.createWidget(
            110, y_top, 220, y_bot,
            1, "FILTER (regex):", 0, self.win, self.fake_xp.WidgetClass_Caption
        )

        self.filter_field = self.fake_xp.createWidget(
            225, y_top, 525, y_bot,
            1, "", 0, self.win, self.fake_xp.WidgetClass_TextField
        )
        self.fake_xp.setWidgetProperty(
            self.filter_field,
            self.fake_xp.Property_TextFieldType,
            self.fake_xp.TextEntryField,
        )

        self.filter_button = self.fake_xp.createWidget(
            530, y_top, 610, y_bot,
            1, "Apply", 0, self.win, self.fake_xp.WidgetClass_Button
        )

        # DATAREF LIST (nudged up to match reclaimed space)
        self.data_caption = self.fake_xp.createWidget(
            110, 705, 1390, 250,
            1, "", 0, self.win, self.fake_xp.WidgetClass_Caption
        )

        # Callbacks
        self.fake_xp.addWidgetCallback(self.win, self._widget_handler)
        self.fake_xp.addWidgetCallback(self.filter_field, self._widget_handler)
        self.fake_xp.addWidgetCallback(self.filter_button, self._widget_handler)

        self._dirty = True

    def close(self) -> None:
        if self.win:
            self.fake_xp.destroyWidget(self.win, 1)
            self.win = None

    # --------------------------------------------------------

    def _widget_handler(
        self,
        msg: XPWidgetMessage | int,
        widget: XPWidgetID | int,
        p1: Any,
        p2: Any,
    ) -> int:
        # TextField commits are event-driven
        if msg == self.fake_xp.Msg_TextFieldChanged and widget == self.filter_field:
            self._filter_text = str(p1)
            return 1

        # Button presses are delivered to the parent window
        if msg == self.fake_xp.Msg_PushButtonPressed and widget == self.filter_button:
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
        enabled, connected, conn_status = self.fake_xp.simless_runner.get_bridge_status()

        if not enabled:
            text = "Bridge: DISABLED"
        else:
            text = f"Bridge: {"CONNECTED" if connected else "DISCONNECTED"} - {conn_status}"

        self.fake_xp.setWidgetDescriptor(self.status_caption, text)

    def _render_datarefs(self) -> None:
        lines: list[str] = []
        lines.append("  D IDX  NAME                                                         W VALUE")
        lines.append("  - ---- ------------------------------------------------------------ - -----")

        for ref in sorted(self.state.refs.values(), key=lambda r: r.meta.idx):
            meta = ref.meta

            if self._filter_regex and not self._filter_regex.search(meta.name):
                continue

            mark = "*" if ref.changed else " "
            dummy = "D" if meta.is_dummy else " "
            lines.append(
                f"{mark} {dummy} {meta.idx:4d} {meta.name:60s} "
                f"{'W' if meta.writable else '-'} {ref.value}"
            )

        self.fake_xp.setWidgetDescriptor(self.data_caption, "\n".join(lines))

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
    def __init__(self, xp: FakeXP):
        self.fake_xp = xp
        self.viewer = DataRefViewer(xp)
        self._attached = False

    @property
    def dm(self) -> DataRefManager:
        return self.fake_xp.dataref_manager

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True

        for ref in self.dm.all_handles():
            self._add_ref(ref)

        self.dm.attach_handle_callback(self._on_new_handle)
        self.viewer.open()

    def detach(self) -> None:
        if not self._attached:
            return
        self._attached = False

        self.dm.detach_handle_callback()
        self.viewer.close()

    def update(self) -> None:
        for state in self.viewer.state.refs.values():
            self._update_value(state)
        self.viewer.refresh()

    def _on_new_handle(self, ref: FakeDataRef) -> None:
        self._add_ref(ref)

    def _add_ref(self, ref: FakeDataRef) -> None:
        if ref.path in self.viewer.state.refs:
            return

        value = self._read_value(ref)

        meta = RefMeta(
            idx=self.viewer._next_idx,
            name=ref.path,
            type=ref.type,
            writable=ref.writable,
            array_size=ref.size,
            is_dummy=not ref.shape_known and not ref.type_known,
        )

        self.viewer.state.refs[ref.path] = RefState(
            meta=meta,
            value=value,
            changed=True,
        )

        self.viewer._next_idx += 1
        self.viewer._dirty = True

    def _update_value(self, state: RefState) -> None:
        ref = self.dm.get_handle(state.meta.name)
        if ref is None:
            return

        new_value = self._read_value(ref)

        state.last_value = state.value
        state.value = new_value
        state.changed = (state.last_value != state.value)
        if state.changed:
            self.viewer._dirty = True

    def _read_value(self, ref: FakeDataRef) -> Any:
        """
        Read the current value of a FakeDataRef using its xp.Type_* dtype.
        """
        fxp = self.fake_xp
        t = ref.type

        # --- Scalars ---
        if t & fxp.Type_Float:
            return fxp.getDataf(ref)

        if t & fxp.Type_Int:
            return fxp.getDatai(ref)

        if t & fxp.Type_Double:
            return fxp.getDatad(ref)

        # --- Arrays ---
        if t & fxp.Type_FloatArray:
            buf = [0.0] * ref.size
            fxp.getDatavf(ref, buf, 0, ref.size)
            return buf

        if t & fxp.Type_IntArray:
            buf = [0] * ref.size
            fxp.getDatavi(ref, buf, 0, ref.size)
            return buf

        if t & fxp.Type_Data:
            buf = bytearray(ref.size)
            fxp.getDatab(ref, buf, 0, ref.size)
            return buf

        return None
