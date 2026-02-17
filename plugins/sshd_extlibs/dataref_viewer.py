from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable

from XPPython3 import xp
from XPPython3.xp_typing import (
    XPWidgetID,
    XPWidgetMessage,
)

LOG_PREFIX = "[DataRefViewer]"


def log(msg: str) -> None:
    xp.log(f"{LOG_PREFIX} {msg}")


# ============================================================
# State model
# ============================================================

@dataclass
class RefMeta:
    idx: int
    name: str
    type: int
    writable: bool
    array_size: int


@dataclass
class RefState:
    meta: RefMeta
    value: Any = None
    last_value: Any = None
    changed: bool = False


class ViewerState:
    def __init__(self):
        self.refs: Dict[int, RefState] = {}
        self.errors: list[str] = []
        # Kept for future use, but not rendered
        self.search: str = ""


# ============================================================
# Widget-based Viewer
# ============================================================

class DataRefViewer:
    def __init__(self):
        self.win: XPWidgetID | None = None
        self.state = ViewerState()
        self._handler: Optional[Callable] = None

        # Single list widget inside the window
        self.caption_list: XPWidgetID | None = None

        log("Viewer initialized")

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def open(self) -> None:
        if self.win is not None:
            log("Viewer window already open")
            return

        log("Creating viewer widget window")

        # Main window (title only in banner)
        self.win = xp.createWidget(
            100, 800, 900, 200,
            1,
            "DataRef Viewer",
            1,
            0,
            xp.WidgetClass_MainWindow,
        )
        xp.setWidgetProperty(self.win, xp.Property_MainWindowHasCloseBoxes, 1)

        # List area only
        self.caption_list = xp.createWidget(
            110, 770, 850, 250,
            1,
            "",
            0,
            int(self.win),
            xp.WidgetClass_Caption,
        )

        # Attach handler
        def handler(msg: XPWidgetMessage, widget: XPWidgetID, p1: Any, p2: Any) -> int:
            return self._widget_handler(msg, widget, p1, p2)

        self._handler = handler
        xp.addWidgetCallback(self.win, handler)

        log("Viewer widget callback attached")

    def close(self) -> None:
        if self.win:
            log("Destroying viewer window")
            xp.destroyWidget(self.win, 1)
            self.win = None

    def clear(self) -> None:
        log("Clearing viewer state")
        self.state.refs.clear()
        self.state.errors.clear()
        self._refresh()

    def update_meta(self, idx: int, name: str, type: int, writable: bool, array_size: int) -> None:
        log(f"META update: idx={idx}, name={name}, writable={writable}, array={array_size}")
        self.state.refs[idx] = RefState(
            meta=RefMeta(idx, name, type, writable, array_size)
        )
        self._refresh()

    def update_value(self, idx: int, value: Any) -> None:
        ref = self.state.refs.get(idx)
        if not ref:
            log(f"UPDATE ignored: unknown idx={idx}")
            return

        ref.last_value = ref.value
        ref.value = value
        ref.changed = (ref.last_value != ref.value)

        self._refresh()

    def set_error(self, text: str) -> None:
        # Keep logging, but do not render errors in the list
        log(f"ERROR: {text}")
        self.state.errors.append(text)
        self.state.errors = self.state.errors[-10:]

    # --------------------------------------------------------
    # Widget handler
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

        if msg == xp.Msg_Draw:
            # Widgets draw themselves; list is just a caption
            return 1

        return 0

    # --------------------------------------------------------
    # Refresh widget text
    # --------------------------------------------------------

    def _refresh(self) -> None:
        """Update list caption based on current state."""

        if not self.win or not self.caption_list:
            return

        lines: list[str] = []
        for idx in sorted(self.state.refs.keys()):
            ref = self.state.refs[idx]
            meta = ref.meta

            # search is not currently exposed in UI; kept for future use
            if self.state.search and self.state.search not in meta.name:
                continue

            mark = "*" if ref.changed else " "
            lines.append(
                f"{mark} {meta.idx:3d}  {meta.name:50s}  "
                f"{'W' if meta.writable else '-'}  {ref.value}"
            )

        xp.setWidgetDescriptor(self.caption_list, "\n".join(lines))


# ============================================================
# Singleton instance
# ============================================================

viewer = DataRefViewer()
