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
from xp_typing import XPWidgetID, XPWidgetMessage

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
# Widget viewer window
# ============================================================

class DataRefViewer:
    LOG_PREFIX = "[FakeXPDataRefViewer]"

    status_caption: XPWidgetID
    filter_label: XPWidgetID
    filter_field: XPWidgetID
    filter_button: XPWidgetID
    data_caption: XPWidgetID

    def __init__(self, xp: FakeXP) -> None:
        self.fake_xp = xp

        self.state = ViewerState()
        self._next_idx: int = 1
        self._dirty: bool = False

        self._window: Optional[XPWidgetID] = None
        self._filter_regex: Optional[Pattern[str]] = None

    @property
    def window(self) -> XPWidgetID:
        if self._window is None:
            raise RuntimeError("WidgetID accessed before creation")
        return self._window

    @window.setter
    def window(self, wid: XPWidgetID) -> None:
        self._window = wid

    @property
    def is_created(self) -> bool:
        return self._window is not None

    @property
    def bridge_status(self) -> str:
        return self._bridge_status

    @bridge_status.setter
    def bridge_status(self, val: str) -> None:
        self._bridge_status = val
        self._dirty = True

    # --------------------------------------------------------

    def create(self) -> None:
        if self._window:
            return

        self._window = self.fake_xp.createWidget(
            100, 800, 1400, 200,
            1,
            "FakeXP DataRef Viewer",
            1,
            0,
            self.fake_xp.WidgetClass_MainWindow,
        )
        self.fake_xp.setWidgetProperty(self.window, self.fake_xp.Property_MainWindowHasCloseBoxes, 1)

        # STATUS (single line)
        self.status_caption = self.fake_xp.createWidget(
            110, 770, 850, 735,
            1, "", 0, self.window, self.fake_xp.WidgetClass_Caption
        )

        # FILTER (single line, moved up)
        y_top = 745
        y_bot = 725

        self.filter_label = self.fake_xp.createWidget(
            110, y_top, 220, y_bot,
            1, "FILTER (regex):", 0, self.window, self.fake_xp.WidgetClass_Caption
        )

        self.filter_field = self.fake_xp.createWidget(
            225, y_top, 525, y_bot,
            1, "", 0, self.window, self.fake_xp.WidgetClass_TextField
        )
        self.fake_xp.setWidgetProperty(
            self.filter_field,
            self.fake_xp.Property_TextFieldType,
            self.fake_xp.TextEntryField,
        )

        self.filter_button = self.fake_xp.createWidget(
            530, y_top, 610, y_bot,
            1, "Apply", 0, self.window, self.fake_xp.WidgetClass_Button
        )

        # DATAREF LIST (nudged up to match reclaimed space)
        self.data_caption = self.fake_xp.createWidget(
            110, 705, 1390, 250,
            1, "", 0, self.window, self.fake_xp.WidgetClass_Caption
        )
        self.fake_xp.setWidgetProperty(self.data_caption, self.fake_xp.Property_Font, self.fake_xp.Font_Basic)

        # Callbacks
        self.fake_xp.addWidgetCallback(self.window, self._widget_handler)
        self.fake_xp.addWidgetCallback(self.filter_field, self._input_handler)

        self._dirty = True

    # --------------------------------------------------------

    def _widget_handler(
            self,
            msg: XPWidgetMessage | int,
            widget: XPWidgetID,
            p1: Any,
            p2: Any,
    ) -> int:
        # Button presses are delivered to the parent window
        if msg == self.fake_xp.Msg_PushButtonPressed and p1 == self.filter_button:
            self._apply_filter()
            return 1

        if msg == self.fake_xp.Message_CloseButtonPushed:
            if self.fake_xp.simless_runner.dataref_viewer.attached:
                self.fake_xp.simless_runner.dataref_viewer.detach()
            return 1

        return 0

    def _input_handler(
            self,
            msg: XPWidgetMessage | int,
            widget: XPWidgetID,
            p1: Any,
            p2: Any,
    ) -> int:
        info = self.fake_xp.widget_manager.require_info(widget)
        return self.fake_xp.widget_manager.handle_input_msg(info, msg, p1, p2, self._apply_filter)

    # --------------------------------------------------------

    def refresh(self) -> None:
        if not self._dirty:
            return

        self._render_status()
        self._render_datarefs()
        self._dirty = False

    # --------------------------------------------------------

    def _render_status(self) -> None:
        status = self.fake_xp.simless_runner.bridge_client.conn_status
        self.fake_xp.setWidgetDescriptor(self.status_caption, status)

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

    def _apply_filter(self) -> None:
        text = self.fake_xp.getWidgetDescriptor(self.filter_field)

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
        self.viewer_widget = DataRefViewer(xp)
        self._attached = False

    @property
    def dm(self) -> DataRefManager:
        return self.fake_xp.dataref_manager

    @property
    def attached(self) -> bool:
        return self._attached

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True

        for ref in self.dm.all_handles():
            self._add_ref(ref)

        self.dm.attach_handle_callback(self._on_new_handle)

        if not self.viewer_widget.is_created:
            self.viewer_widget.create()
        self.fake_xp.showWidget(self.viewer_widget.window)

    def detach(self) -> None:
        if not self._attached:
            return
        self._attached = False

        self.dm.detach_handle_callback()

        self.viewer_widget.state.refs.clear()
        self.fake_xp.hideWidget(self.viewer_widget.window)

    def update(self) -> None:
        for state in self.viewer_widget.state.refs.values():
            self._update_value(state)
        self.viewer_widget.refresh()

    def _on_new_handle(self, ref: FakeDataRef) -> None:
        self._add_ref(ref)

    def _add_ref(self, ref: FakeDataRef) -> None:
        if ref.path in self.viewer_widget.state.refs:
            return

        value = self._read_value(ref)

        meta = RefMeta(
            idx=self.viewer_widget._next_idx,
            name=ref.path,
            type=ref.type,
            writable=ref.writable,
            array_size=ref.size,
            is_dummy=not ref.shape_known and not ref.type_known,
        )

        self.viewer_widget.state.refs[ref.path] = RefState(
            meta=meta,
            value=value,
            changed=True,
        )

        self.viewer_widget._next_idx += 1
        self.viewer_widget._dirty = True

    def _update_value(self, state: RefState) -> None:
        ref = self.dm.get_handle(state.meta.name)
        if ref is None:
            return

        new_value = self._read_value(ref)

        state.last_value = state.value
        state.value = new_value
        state.changed = (state.last_value != state.value)
        if state.changed:
            self.viewer_widget._dirty = True

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
