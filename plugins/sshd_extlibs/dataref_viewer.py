# sshd_extlibs/dataref_viewer.py
# ===========================================================================
# DataRefViewer — widget‑based inspector for managed DataRefs
#
# ROLE
#   Provide a lightweight, reload‑safe UI for inspecting DataRefs tracked
#   by the DataRefManager. The viewer is environment‑agnostic and works
#   identically in production (XPPython3) and simless (FakeXP) plugins.
#
# DESIGN
#   • Viewer is instantiated fresh on plugin reload; all state lives in
#     the class instance (no globals beyond the module‑level singleton).
#   • Polling is plugin‑driven: plugins schedule viewer.poll() in a
#     flightloop. The viewer never drives its own timing.
#   • Only DataRefManager is authoritative. Viewer never queries X‑Plane
#     directly, never touches FakeXP internals, and never consumes bridge
#     messages. All metadata and values come from DataRefManager.
#   • Redraws are incremental: widget text is updated only when a managed
#     DataRef is added, removed, or its value changes.
#
# UI NOTES
#   • Window creation/destruction is explicit via open()/close().
#   • clear() resets viewer state without destroying the window.
#   • Dummy DataRefs (spec.is_dummy) are marked in the display.
#   • Changed values are marked per‑poll for visual inspection.
#
# CORE INVARIANTS
#   • No inference or hidden state; viewer reflects DataRefManager exactly.
#   • No X‑Plane‑specific assumptions; works in both real and simless XP.
#   • Reload‑safe: plugin reload → new viewer instance → clean state.
# ===========================================================================

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
        self.errors: list[str] = []
        # Kept for future use, but not rendered
        self.search: str = ""


# ============================================================
# Widget-based Viewer
# ============================================================

class DataRefViewer:
    def __init__(self) -> None:
        self.win: XPWidgetID | None = None
        self.state = ViewerState()
        self._handler: Optional[Callable] = None

        # Single list widget inside the window
        self.caption_list: XPWidgetID | None = None

        # Tracking for efficient redraw
        self._dirty: bool = False
        self._next_idx: int = 1  # stable indices per path

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
            self.win,
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
            self.caption_list = None
            self._handler = None

    def clear(self) -> None:
        log("Clearing viewer state")
        self.state.refs.clear()
        self.state.errors.clear()
        self._next_idx = 1
        self._dirty = True
        self._refresh()

    def poll(self) -> None:
        """Poll DataRefManager and update state; redraw only on change."""
        mgr = getattr(xp, "_dataref_manager", None)
        if mgr is None:
            return

        changed = False

        # Current managed paths
        try:
            paths = list(mgr.all_paths())
        except Exception as exc:
            log(f"DataRefManager all_paths() failed: {exc!r}")
            return

        current_paths = set(paths)
        known_paths = set(self.state.refs.keys())

        # Removed paths
        removed = known_paths - current_paths
        if removed:
            for path in removed:
                self.state.refs.pop(path, None)
            changed = True

        # Added/updated paths
        for path in paths:
            try:
                spec = mgr.get_spec(path)
            except Exception as exc:
                log(f"DataRefManager get_spec({path!r}) failed: {exc!r}")
                continue

            if spec is None:
                continue

            try:
                value = mgr.get_value(path)
            except Exception as exc:
                log(f"DataRefManager get_value({path!r}) failed: {exc!r}")
                continue

            ref = self.state.refs.get(path)
            if ref is None:
                idx = self._next_idx
                self._next_idx += 1
                meta = RefMeta(
                    idx=idx,
                    name=path,
                    type=spec.type,
                    writable=spec.writable,
                    array_size=getattr(spec, "array_size", 0),
                    is_dummy=getattr(spec, "is_dummy", False),
                )
                ref = RefState(meta=meta, value=value, last_value=None, changed=True)
                self.state.refs[path] = ref
                changed = True
            else:
                # Update meta in case spec changed
                ref.meta.type = spec.type
                ref.meta.writable = spec.writable
                ref.meta.array_size = getattr(spec, "array_size", ref.meta.array_size)
                ref.meta.is_dummy = getattr(spec, "is_dummy", ref.meta.is_dummy)

                ref.last_value = ref.value
                ref.value = value
                ref.changed = (ref.last_value != ref.value)
                if ref.changed:
                    changed = True

        if changed:
            self._dirty = True
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
        """Update list caption based on current state, only when dirty."""
        if not self._dirty:
            return

        if not self.win or not self.caption_list:
            self._dirty = False
            return

        lines: list[str] = []
        # Sort by idx to keep stable ordering
        refs_sorted = sorted(self.state.refs.values(), key=lambda r: r.meta.idx)

        for ref in refs_sorted:
            meta = ref.meta

            # search is not currently exposed in UI; kept for future use
            if self.state.search and self.state.search not in meta.name:
                continue

            mark = "*" if ref.changed else " "
            dummy = "D" if meta.is_dummy else " "
            lines.append(
                f"{mark}{dummy} {meta.idx:3d}  {meta.name:50s}  "
                f"{'W' if meta.writable else '-'}  {ref.value}"
            )

        xp.setWidgetDescriptor(self.caption_list, "\n".join(lines))
        self._dirty = False
