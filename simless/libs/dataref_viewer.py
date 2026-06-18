# simless/libs/fake_xp_dataref_viewer.py
# ===========================================================================
# FakeXPDataRefViewer — widget-based inspector for all FakeDataRefs
# ===========================================================================

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Pattern, TYPE_CHECKING

from xp_typing import XPWidgetID, XPWidgetMessage

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


@dataclass
class CacheEntry:
    path: str
    type: int
    size: int
    writable: bool
    value: Any  # Python object (int, float, list, bytes, etc.)

    def to_json(self) -> str:
        data = asdict(self)

        # Encode Type_Data (bytes/bytearray) as base64 string
        if isinstance(self.value, (bytes, bytearray)):
            data["value"] = {
                "encoding": "base64",
                "data": base64.b64encode(self.value).decode("ascii")
            }

        return json.dumps(data)

    @staticmethod
    def from_json(s: str) -> "CacheEntry":
        data = json.loads(s)

        # Decode Type_Data if present
        if isinstance(data.get("value"), dict) and data["value"].get("encoding") == "base64":
            b64 = data["value"]["data"]
            data["value"] = base64.b64decode(b64)

        return CacheEntry(**data)


class DataRefCache:
    """
    Dict-backed cache of DataRef metadata.
    One line per dataref, left-justified, min 3 spaces between columns.
    """

    HEADER = (
        "# DataRef Cache to ensure correct dataref shape/value when offline\n"
        "#PATH                                                                                TYPE                                 SIZE    WRITEABLE   VALUE\n"
    )

    def __init__(self, fake_xp: FakeXP) -> None:
        self.fake_xp = fake_xp
        self._cache: Dict[str, CacheEntry] = {}

        self.from_file()

    def get_cached_info(self, path: str) -> Optional[CacheEntry]:
        return self._cache.get(path)

    def to_file(self):
        with open(self.fake_xp._dataref_cache_path, "w", encoding="utf-8") as f:
            for entry in self._cache.values():
                f.write(entry.to_json() + "\n")

    def from_file(self):
        self._cache.clear()

        try:
            with open(self.fake_xp._dataref_cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    entry = CacheEntry.from_json(line)
                    self._cache[entry.path] = entry

        except FileNotFoundError:
            pass

    def update(self):
        for ref in self.fake_xp.dataref_manager.all_handles():
            if ref.dummy or ref.cached:
                continue
            self._cache[ref.path] = CacheEntry(
                path=ref.path,
                type=ref.type,
                size=ref.size,
                writable=ref.writable,
                value=ref.value
            )

        self.to_file()

    def clear(self):
        self._cache.clear()
        with open(self.fake_xp._dataref_cache_path, "w", encoding="utf-8") as f:
            f.write(self.HEADER)


class DataRefViewer:
    LOG_PREFIX = "[FakeXPDataRefViewer]"

    status_caption: XPWidgetID
    filter_label: XPWidgetID
    filter_field: XPWidgetID
    filter_button: XPWidgetID
    data_caption: XPWidgetID
    cache_save_button: XPWidgetID
    cache_clear_button: XPWidgetID

    def __init__(self, xp: FakeXP) -> None:
        self.fake_xp = xp

        self._next_idx: int = 1
        self._dirty: bool = False
        self._bridge_status: str = ""
        self._last_dataref_render = time.monotonic()

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

        # DATAREF CACHE CONTROLS (same row as filter)
        self.fake_xp.createWidget(
            660, y_top, 740, y_bot,
            1, "Dataref Cache:", 0, self.window, self.fake_xp.WidgetClass_Caption
        )

        self.cache_save_button = self.fake_xp.createWidget(
            760, y_top, 800, y_bot,
            1, "Save", 0, self.window, self.fake_xp.WidgetClass_Button
        )

        self.cache_clear_button = self.fake_xp.createWidget(
            810, y_top, 870, y_bot,
            1, "Delete", 0, self.window, self.fake_xp.WidgetClass_Button
        )

        # Register callbacks
        self.fake_xp.addWidgetCallback(self.cache_save_button, self._widget_handler)
        self.fake_xp.addWidgetCallback(self.cache_clear_button, self._widget_handler)

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
        if msg == self.fake_xp.Msg_PushButtonPressed:
            if p1 == self.filter_button:
                self._apply_filter()
                return 1
            if p1 == self.cache_clear_button:
                self.fake_xp.dataref_cache.clear()
                return 1
            if p1 == self.cache_save_button:
                self.fake_xp.dataref_cache.update()
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

    def menu_cmd(self, cmd, phase, refcon):
        if phase == self.fake_xp.CommandBegin:
            if not self.is_created:
                self.create()
            elif not self.fake_xp.isWidgetVisible(self.window):
                self.fake_xp.showWidget(self.window)
                self.fake_xp.setKeyboardFocus(self.filter_field)

    def refresh(self) -> None:
        if not self.is_created:
            return
        if not self.fake_xp.isWidgetVisible(self.window):
            return
        if self.fake_xp.dataref_manager.last_updated > self._last_dataref_render:
            self._dirty = True
        if not self._dirty:
            return

        self._render_status()
        recent_changes = self._render_datarefs()
        if not recent_changes:
            self._dirty = False

    # --------------------------------------------------------

    def _render_status(self) -> None:
        status = self.fake_xp.simless_runner.bridge_client.conn_status
        self.fake_xp.setWidgetDescriptor(self.status_caption, status)

    def _render_datarefs(self) -> bool:
        lines: list[str] = ["  D IDX  NAME                                                         W VALUE",
                            "  - ---- ------------------------------------------------------------ - -----"]

        recent = False
        for ref in self.fake_xp.dataref_manager.all_handles():
            if self._filter_regex and not self._filter_regex.search(ref.path):
                continue

            now = time.monotonic()
            mark = " "
            if now - ref.last_modified <= 10:
                mark = "*"
                recent = True
            lines.append(
                f"{mark} {ref.phase} {ref.df_id:4d} {ref.path:60s} "
                f"{'W' if ref.writable else ' '} {ref.value}"
            )

        self.fake_xp.setWidgetDescriptor(self.data_caption, "\n".join(lines))
        return recent

    def _apply_filter(self) -> None:
        text = self.fake_xp.getWidgetDescriptor(self.filter_field)

        if not text:
            self._filter_regex = None
        else:
            self._filter_regex = re.compile(re.escape(text))

        self._dirty = True
