# ===========================================================================
# FakeXP
# Public API surface that emulates xp.* for XPPython3 plugins.
#
# Responsibilities:
#   - DataRef access (get/set/find)
#   - Dummy-handle detection
#   - Delegating dummy promotion to FakeXPRunner
#   - Widget API surface
#   - Graphics API surface
#   - Flightloop scheduling
# ===========================================================================

import time
from typing import Any, Callable, Dict, List, Sequence

import XPPython3
from plugins.extensions.datarefs import DataRefManager

from simless.libs.fake_xp_runner import FakeXPRunner
from simless.libs.fake_xp_widget import (
    FakeXPWidgets,
    xpWidgetClass_MainWindow,
    xpWidgetClass_SubWindow,
    xpWidgetClass_Button,
    xpWidgetClass_TextField,
    xpWidgetClass_Caption,
    xpWidgetClass_ScrollBar,
    xpWidgetClass_ListBox,
    xpWidgetClass_Custom,
    Property_ScrollValue,
    Property_ScrollMin,
    Property_ScrollMax,
    Property_ListItems,
    Property_ListSelection,
    Msg_MouseDown,
    Msg_MouseDrag,
    Msg_MouseUp,
    Msg_KeyPress,
)

from simless.libs.fake_xp_graphics import FakeXPGraphics


class FakeXP:
    def __init__(self, *, debug: bool = False):
        self.debug_enabled = debug

        # DataRef tables
        self._handles: Dict[str, int] = {}
        self._info: Dict[int, tuple[int, bool, bool, int]] = {}
        self._values: Dict[int, Any] = {}

        # Handle counters
        self._next_handle: int = 1
        self._next_dummy: int = -1

        # Dummy lookup
        self._pending: Dict[int, str] = {}

        # Runner reference (set by FakeXPRunner)
        self._runner: FakeXPRunner | None = None

        # Optional DataRefManager
        self._dataref_manager: DataRefManager | None = None

        # Plugin list (populated by runner)
        self._plugins: List[Any] = []

        # Flightloops
        self._flightloops: List[Callable[[float], None]] = []
        self._flightloop_handles: List[dict] = []
        self._last_frame_time = time.time()

        # Widgets + Graphics
        self.widgets = FakeXPWidgets(self)
        self.graphics = FakeXPGraphics(self)

        # Loop control
        self._running = False

        # Bind xp.* into XPPython3
        XPPython3.xp = self

        xp = XPPython3.xp

        # Widget classes
        xp.WidgetClass_MainWindow = xpWidgetClass_MainWindow
        xp.WidgetClass_SubWindow = xpWidgetClass_SubWindow
        xp.WidgetClass_Button = xpWidgetClass_Button
        xp.WidgetClass_TextField = xpWidgetClass_TextField
        xp.WidgetClass_Caption = xpWidgetClass_Caption
        xp.WidgetClass_ScrollBar = xpWidgetClass_ScrollBar
        xp.WidgetClass_ListBox = xpWidgetClass_ListBox
        xp.WidgetClass_Custom = xpWidgetClass_Custom

        # Widget properties
        xp.Property_ScrollValue = Property_ScrollValue
        xp.Property_ScrollMin = Property_ScrollMin
        xp.Property_ScrollMax = Property_ScrollMax
        xp.Property_ListItems = Property_ListItems
        xp.Property_ListSelection = Property_ListSelection

        # Widget messages
        xp.Msg_MouseDown = Msg_MouseDown
        xp.Msg_MouseDrag = Msg_MouseDrag
        xp.Msg_MouseUp = Msg_MouseUp
        xp.Msg_KeyPress = Msg_KeyPress

        # Widget API passthrough
        xp.createWidget = self.widgets.createWidget
        xp.killWidget = self.widgets.killWidget
        xp.setWidgetGeometry = self.widgets.setWidgetGeometry
        xp.getWidgetGeometry = self.widgets.getWidgetGeometry
        xp.getWidgetExposedGeometry = self.widgets.getWidgetExposedGeometry
        xp.showWidget = self.widgets.showWidget
        xp.hideWidget = self.widgets.hideWidget
        xp.isWidgetVisible = self.widgets.isWidgetVisible
        xp.isWidgetInFront = self.widgets.isWidgetInFront
        xp.bringWidgetToFront = self.widgets.bringWidgetToFront
        xp.pushWidgetBehind = self.widgets.pushWidgetBehind
        xp.getParentWidget = self.widgets.getParentWidget
        xp.getWidgetClass = self.widgets.getWidgetClass
        xp.getWidgetUnderlyingWindow = self.widgets.getWidgetUnderlyingWindow
        xp.setWidgetDescriptor = self.widgets.setWidgetDescriptor
        xp.getWidgetDescriptor = self.widgets.getWidgetDescriptor
        xp.getWidgetForLocation = self.widgets.getWidgetForLocation
        xp.setKeyboardFocus = self.widgets.setKeyboardFocus
        xp.loseKeyboardFocus = self.widgets.loseKeyboardFocus
        xp.setWidgetProperty = self.widgets.setWidgetProperty
        xp.getWidgetProperty = self.widgets.getWidgetProperty
        xp.addWidgetCallback = self.widgets.addWidgetCallback
        xp.sendWidgetMessage = self.widgets.sendWidgetMessage

    # ----------------------------------------------------------------------
    # Debug
    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if self.debug_enabled:
            print(f"[FakeXP] {msg}")

    def log(self, msg: str) -> None:
        print(f"[FakeXP] {msg}")

    def _quit(self):
        """
        Internal sim-less endpoint.
        Allows plugins to request termination of the FakeXP run loop.
        """
        if hasattr(self, "_runner") and self._runner:
            self._runner.end_run_loop()

    # ----------------------------------------------------------------------
    # DataRef API
    # ----------------------------------------------------------------------
    def findDataRef(self, path: str) -> int:
        if path in self._handles:
            return self._handles[path]

        dummy = self._next_dummy
        self._next_dummy -= 1

        self._pending[dummy] = path
        self._dbg(f"[Strict] findDataRef('{path}') -> dummy {dummy}")

        return dummy

    def getDataRefInfo(self, handle: int):
        return self._info.get(handle, (0, False, False, 0))

    def _promote_dummy(self, dummy: int, xp_type: int, is_array: bool, default):
        """
        Promote a dummy handle to a real dataref.
        FakeXP now owns the entire promotion process.
        """
        path = self._pending.pop(dummy, None)
        if path is None:
            raise KeyError(f"Unknown dummy handle: {dummy}")

        # Allocate real handle
        real = self._next_handle
        self._next_handle += 1

        # Register real dataref
        self._handles[path] = real
        self._info[real] = (xp_type, True, is_array, 0)
        self._values[real] = default

        self._dbg(f"[Strict] Promoted dummy {dummy} -> real dataref '{path}'")

        # Notify DataRefManager if present
        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(real)

        return real

    # ----------------------------------------------------------------------
    # Helper used by all get/set accessors
    # ----------------------------------------------------------------------
    def _promote_if_dummy(self, handle: int, xp_type: int, is_array: bool, default):
        if handle >= 0:
            return handle
        return self._promote_dummy(handle, xp_type, is_array, default)

    # ----------------------------------------------------------------------
    # Datai
    # ----------------------------------------------------------------------
    def getDatai(self, handle: int) -> int:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 1, False, 0)
        return int(self._values.get(handle, 0))

    def setDatai(self, handle: int, value: int) -> None:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 1, False, int(value))
        self._values[handle] = int(value)

    # ----------------------------------------------------------------------
    # Dataf
    # ----------------------------------------------------------------------
    def getDataf(self, handle: int) -> float:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 2, False, 0.0)
        return float(self._values.get(handle, 0.0))

    def setDataf(self, handle: int, value: float) -> None:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 2, False, float(value))
        self._values[handle] = float(value)

    def registerDataRef(self, path: str, xpType: int, isArray: bool,
                        writable: bool, defaultValue):
        # Allocate real handle
        real = self._next_handle
        self._next_handle += 1

        # Register
        self._handles[path] = real
        self._info[real] = (xpType, writable, isArray, 0)
        self._values[real] = defaultValue

        self._dbg(f"[Strict] registerDataRef('{path}') -> handle {real}")

        # Notify DataRefManager if present
        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(real)

        return real

    # ----------------------------------------------------------------------
    # Datad
    # ----------------------------------------------------------------------
    def getDatad(self, handle: int) -> float:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 2, False, 0.0)
        return float(self._values.get(handle, 0.0))

    def setDatad(self, handle: int, value: float) -> None:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 2, False, float(value))
        self._values[handle] = float(value)

    # ----------------------------------------------------------------------
    # Datavf
    # ----------------------------------------------------------------------
    def getDatavf(self, handle: int, count: int) -> List[float]:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 8, True, [])
        arr = self._values.get(handle, [])
        return [float(v) for v in arr[:count]]

    def setDatavf(self, handle: int, values: Sequence[float]) -> None:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 8, True, list(values))
        self._values[handle] = [float(v) for v in values]

    # ----------------------------------------------------------------------
    # Datavi
    # ----------------------------------------------------------------------
    def getDatavi(self, handle: int) -> List[int]:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 16, True, [])
        arr = self._values.get(handle, [])
        return [int(v) for v in arr]

    def setDatavi(self, handle: int, values: Sequence[int]) -> None:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 16, True, list(values))
        self._values[handle] = [int(v) for v in values]

    # ----------------------------------------------------------------------
    # Datab
    # ----------------------------------------------------------------------
    def getDatab(self, handle: int) -> bytes:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 32, True, b"")
        return bytes(self._values.get(handle, b""))

    def setDatab(self, handle: int, data: bytes) -> None:
        if handle < 0:
            handle = self._promote_if_dummy(handle, 32, True, bytes(data))
        self._values[handle] = bytes(data)

    # ----------------------------------------------------------------------
    # Flightloop API
    # ----------------------------------------------------------------------
    def registerFlightLoopCallback(self, cb):
        self._flightloops.append(cb)

    def createFlightLoop(self, callback):
        handle = len(self._flightloop_handles)
        self._flightloop_handles.append({
            "callback": callback,
            "next_run": None,
            "active": True,
        })
        return handle

    def scheduleFlightLoop(self, handle, interval):
        if 0 <= handle < len(self._flightloop_handles):
            entry = self._flightloop_handles[handle]
            if entry["active"]:
                now = time.time()
                entry["next_run"] = now if interval < 0 else now + interval

    def destroyFlightLoop(self, handle):
        if 0 <= handle < len(self._flightloop_handles):
            entry = self._flightloop_handles[handle]
            entry["active"] = False
            entry["callback"] = lambda *args, **kwargs: 0
            entry["next_run"] = None
