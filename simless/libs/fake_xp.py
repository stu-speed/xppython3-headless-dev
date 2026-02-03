# ===========================================================================
# FakeXP — unified xp.* façade for simless plugin execution
#
# Provides a complete, in‑memory implementation of the xp.* API surface used
# by XPPython3 plugins. FakeXP acts as the central coordinator for all simless
# subsystems: DataRefs, Widgets, Graphics, and Utilities.
#
# Responsibilities:
#   • Expose the xp.* namespace expected by plugins (widgets, graphics,
#     datarefs, utilities, flightloops)
#   • Maintain deterministic, in‑memory state for all subsystems
#   • Provide strongly typed FakeRefInfo handles for DataRefs
#   • Route widget and graphics calls to FakeXPWidgets / FakeXPGraphics
#   • Forward all flightloop registration/scheduling to FakeXPRunner
#   • Integrate with FakeXPRunner for lifecycle and frame pumping
#
# Behavior notes:
#   • All xp.* functions are bound directly onto the FakeXP instance
#   • DataRefs support dummy‑ref promotion and default initialization
#   • Widgets and graphics are backed by DearPyGui when GUI mode is enabled
#   • All operations are deterministic and safe for CI/test automation
#
# Design goals:
#   • Provide a drop‑in xp.* environment for plugin authors
#   • Mirror X‑Plane semantics closely while remaining pure Python
#   • Keep subsystem boundaries explicit and maintainable
# ===========================================================================

from __future__ import annotations

import os
from dataclasses import dataclass
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


# ===========================================================================
# FakeRefInfo — strongly typed handle for simless mode
# ===========================================================================

@dataclass(slots=True, unsafe_hash=True)
class FakeDataRefInfo:
    """
    Strongly-typed DataRef representation for FakeXP.

    This object *is* the handle in simless mode and structurally matches
    FakeRefInfoProto used in XPInterface typing.
    """

    path: str
    xp_type: int | None
    writable: bool
    is_array: bool
    size: int = 0
    dummy: bool = False
    value: Any = None


# ===========================================================================
# FakeXP implementation
# ===========================================================================

class FakeXP:
    def __init__(self, *, debug: bool = False) -> None:
        self.debug_enabled: bool = debug

        # DataRef tables
        self._handles: Dict[str, FakeDataRefInfo] = {}
        self._dummy_refs: Dict[str, FakeDataRefInfo] = {}
        self._values: Dict[FakeDataRefInfo, Any] = {}

        # Runner reference (set by FakeXPRunner)
        self._runner: FakeXPRunner | None = None

        # Optional DataRefManager (bound via bind_dataref_manager)
        self._dataref_manager: DataRefManager | None = None

        # Plugin list (populated by runner)
        self._plugins: List[Any] = []

        # Disabled plugin tracking (used by runner to skip callbacks)
        self._disabled_plugins: set[int] = set()

        # Widgets + Graphics
        self.widgets = FakeXPWidgets(self)
        self.graphics = FakeXPGraphics(self)

        # Sim time (advanced by runner)
        self._sim_time: float = 0.0

        # Loop control (used by runner)
        self._running: bool = False

        # Keyboard focus
        self._keyboard_focus: int | None = None

        # Bind xp.* into XPPython3 (always overwrite for test isolation)
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

        # Widget API passthrough (xp.*)
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

        # Also expose widget API on the FakeXP instance itself
        self.createWidget = self.widgets.createWidget
        self.killWidget = self.widgets.killWidget
        self.setWidgetGeometry = self.widgets.setWidgetGeometry
        self.getWidgetGeometry = self.widgets.getWidgetGeometry
        self.getWidgetExposedGeometry = self.widgets.getWidgetExposedGeometry
        self.showWidget = self.widgets.showWidget
        self.hideWidget = self.widgets.hideWidget
        self.isWidgetVisible = self.widgets.isWidgetVisible
        self.isWidgetInFront = self.widgets.isWidgetInFront
        self.bringWidgetToFront = self.widgets.bringWidgetToFront
        self.pushWidgetBehind = self.widgets.pushWidgetBehind
        self.getParentWidget = self.widgets.getParentWidget
        self.getWidgetClass = self.widgets.getWidgetClass
        self.getWidgetUnderlyingWindow = self.widgets.getWidgetUnderlyingWindow
        self.setWidgetDescriptor = self.widgets.setWidgetDescriptor
        self.getWidgetDescriptor = self.widgets.getWidgetDescriptor
        self.getWidgetForLocation = self.widgets.getWidgetForLocation
        self.setKeyboardFocus = self.widgets.setKeyboardFocus
        self.loseKeyboardFocus = self.widgets.loseKeyboardFocus
        self.setWidgetProperty = self.widgets.setWidgetProperty
        self.getWidgetProperty = self.widgets.getWidgetProperty
        self.addWidgetCallback = self.widgets.addWidgetCallback
        self.sendWidgetMessage = self.widgets.sendWidgetMessage

    # ----------------------------------------------------------------------
    # Debug / lifecycle headless methods
    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if self.debug_enabled:
            print(f"[FakeXP] {msg}")

    def _run_plugin_lifecycle(self, plugin_names, *, debug=False, enable_gui=True, run_time=-1.0):
        runner = FakeXPRunner(self, enable_gui=enable_gui, run_time=run_time, debug=debug)
        runner.run_plugin_lifecycle(plugin_names)

    def _quit(self) -> None:
        if self._runner is not None:
            self._runner.end_run_loop()

    # ----------------------------------------------------------------------
    # Base xp methods
    # ----------------------------------------------------------------------
    def getMyID(self) -> int:
        # For now, a single-plugin ID; can be extended to real IDs later.
        return 1

    def disablePlugin(self, plugin_id: int) -> None:
        self._disabled_plugins.add(plugin_id)
        self._dbg(f"disablePlugin({plugin_id}) → marked disabled")

    def log(self, msg: str) -> None:
        print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # DataRefManager binding
    # ----------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: DataRefManager) -> None:
        self._dataref_manager = mgr

    # ----------------------------------------------------------------------
    # Optional simless auto-registration
    # ----------------------------------------------------------------------
    def fake_register_dataref(
        self,
        path: str,
        default: Any | None,
        writable: bool | None,
    ) -> FakeDataRefInfo:
        if path in self._handles:
            return self._handles[path]

        ref = FakeDataRefInfo(
            path=path,
            xp_type=None,
            writable=bool(writable) if writable is not None else True,
            is_array=isinstance(default, (list, bytes, bytearray)),
            size=0,
            dummy=False,
            value=default,
        )
        self._handles[path] = ref
        self._values[ref] = default
        self._dbg(f"[FakeXP] fake_register_dataref('{path}')")
        return ref

    # ----------------------------------------------------------------------
    # DataRef API (FakeXP-only, always FakeRefInfo)
    # ----------------------------------------------------------------------
    def findDataRef(self, path: str) -> FakeDataRefInfo | None:
        if path in self._handles:
            return self._handles[path]

        if path in self._dummy_refs:
            return self._dummy_refs[path]

        ref = FakeDataRefInfo(
            path=path,
            xp_type=None,
            writable=False,
            is_array=False,
            size=0,
            dummy=True,
            value=None,
        )
        self._dummy_refs[path] = ref
        self._dbg(f"[Strict] findDataRef('{path}') -> dummy")
        return ref

    def getDataRefInfo(self, handle: FakeDataRefInfo) -> FakeDataRefInfo:
        return handle

    # ----------------------------------------------------------------------
    # Promotion
    # ----------------------------------------------------------------------
    def _promote(
        self,
        ref: FakeDataRefInfo,
        xp_type: int,
        is_array: bool,
        default: Any,
    ) -> FakeDataRefInfo:
        if not ref.dummy:
            return ref

        ref.dummy = False
        ref.xp_type = xp_type
        ref.is_array = is_array
        ref.value = default

        self._dummy_refs.pop(ref.path, None)
        self._handles[ref.path] = ref
        self._values[ref] = default

        self._dbg(f"[Strict] Promoted '{ref.path}' to real dataref")

        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

        return ref

    def _ensure_real(
        self,
        handle: FakeDataRefInfo,
        xp_type: int,
        is_array: bool,
        default: Any,
    ) -> FakeDataRefInfo:
        if handle.dummy:
            return self._promote(handle, xp_type, is_array, default)
        return handle

    # ----------------------------------------------------------------------
    # Datai
    # ----------------------------------------------------------------------
    def getDatai(self, handle: FakeDataRefInfo) -> int:
        ref = self._ensure_real(handle, xp_type=1, is_array=False, default=0)
        return int(self._values.get(ref, ref.value or 0))

    def setDatai(self, handle: FakeDataRefInfo, value: int) -> None:
        ref = self._ensure_real(handle, xp_type=1, is_array=False, default=int(value))
        v = int(value)
        ref.value = v
        self._values[ref] = v
        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Dataf
    # ----------------------------------------------------------------------
    def getDataf(self, handle: FakeDataRefInfo) -> float:
        ref = self._ensure_real(handle, xp_type=2, is_array=False, default=0.0)
        return float(self._values.get(ref, ref.value or 0.0))

    def setDataf(self, handle: FakeDataRefInfo, value: float) -> None:
        ref = self._ensure_real(handle, xp_type=2, is_array=False, default=float(value))
        v = float(value)
        ref.value = v
        self._values[ref] = v
        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datad (double mapped to float)
    # ----------------------------------------------------------------------
    def getDatad(self, handle: FakeDataRefInfo) -> float:
        ref = self._ensure_real(handle, xp_type=4, is_array=False, default=0.0)
        return float(self._values.get(ref, ref.value or 0.0))

    def setDatad(self, handle: FakeDataRefInfo, value: float) -> None:
        ref = self._ensure_real(handle, xp_type=4, is_array=False, default=float(value))
        v = float(value)
        ref.value = v
        self._values[ref] = v
        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datavf (float array)
    # ----------------------------------------------------------------------
    def getDatavf(self, handle: FakeDataRefInfo) -> List[float]:
        ref = self._ensure_real(handle, xp_type=8, is_array=True, default=[])
        arr = self._values.get(ref, ref.value or [])
        return [float(v) for v in arr]

    def setDatavf(self, handle: FakeDataRefInfo, values: Sequence[float]) -> None:
        ref = self._ensure_real(handle, xp_type=8, is_array=True, default=list(values))
        arr = [float(v) for v in values]
        ref.value = arr
        self._values[ref] = arr
        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datavi (int array)
    # ----------------------------------------------------------------------
    def getDatavi(self, handle: FakeDataRefInfo) -> List[int]:
        ref = self._ensure_real(handle, xp_type=16, is_array=True, default=[])
        arr = self._values.get(ref, ref.value or [])
        return [int(v) for v in arr]

    def setDatavi(self, handle: FakeDataRefInfo, values: Sequence[int]) -> None:
        ref = self._ensure_real(handle, xp_type=16, is_array=True, default=list(values))
        arr = [int(v) for v in values]
        ref.value = arr
        self._values[ref] = arr
        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datab (byte array)
    # ----------------------------------------------------------------------
    def getDatab(self, handle: FakeDataRefInfo) -> bytes:
        ref = self._ensure_real(handle, xp_type=32, is_array=True, default=b"")
        data = self._values.get(ref, ref.value or b"")
        return bytes(data)

    def setDatab(self, handle: FakeDataRefInfo, data: bytes) -> None:
        ref = self._ensure_real(handle, xp_type=32, is_array=True, default=bytes(data))
        b = bytes(data)
        ref.value = b
        self._values[ref] = b
        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # registerDataRef (explicit registration, used by runner/tests)
    # ----------------------------------------------------------------------
    def registerDataRef(
        self,
        path: str,
        xpType: int,
        isArray: bool,
        writable: bool,
        defaultValue: Any,
    ) -> FakeDataRefInfo:
        ref = FakeDataRefInfo(
            path=path,
            xp_type=xpType,
            writable=writable,
            is_array=isArray,
            size=0,
            dummy=False,
            value=defaultValue,
        )
        self._handles[path] = ref
        self._values[ref] = defaultValue

        self._dbg(f"[Strict] registerDataRef('{path}') -> real")

        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

        return ref

    # ----------------------------------------------------------------------
    # Flightloop API — XPPython3-accurate, forwarded to runner
    # ----------------------------------------------------------------------
    def registerFlightLoopCallback(self, cb: Callable[[float], float], interval: float) -> None:
        """
        Legacy XPPython3 API:
            xp.registerFlightLoopCallback(cb, interval)
        """
        if self._runner is None:
            raise RuntimeError("registerFlightLoopCallback called before runner is attached")
        plugin_id = self.getMyID()
        self._runner.register_legacy_flightloop(plugin_id, cb, interval)

    def createFlightLoop(self, params) -> dict:
        """
        Modern XPPython3 API:
            handle = xp.createFlightLoop(params)
        """
        if self._runner is None:
            raise RuntimeError("createFlightLoop called before runner is attached")
        plugin_id = self.getMyID()
        return self._runner.create_modern_flightloop(plugin_id, params)

    def scheduleFlightLoop(self, handle: dict, interval: float, relative: int) -> None:
        """
        Modern XPPython3 API:
            xp.scheduleFlightLoop(handle, interval, relative)
        """
        if self._runner is None:
            raise RuntimeError("scheduleFlightLoop called before runner is attached")
        self._runner.schedule_modern_flightloop(handle, interval, relative)

    # ----------------------------------------------------------------------
    # XPWidgets (extra helpers)
    # ----------------------------------------------------------------------
    def getWidgetWithFocus(self) -> int | None:
        return self._keyboard_focus

    # ----------------------------------------------------------------------
    # XPLMGraphics (delegated to FakeXPGraphics)
    # ----------------------------------------------------------------------
    def registerDrawCallback(
        self,
        callback: Callable[[int, int, Any], int],
        phase: int,
        before: int,
        refcon: Any,
    ) -> None:
        def wrapper() -> None:
            callback(0, 0, refcon)

        self.graphics.registerDrawCallback(wrapper)

    def unregisterDrawCallback(
        self,
        callback: Callable[[int, int, Any], int],
        phase: int,
        before: int,
        refcon: Any,
    ) -> None:
        # No-op for now; tests don't require unregister semantics
        return None

    def drawString(
        self,
        x: float,
        y: float,
        text: str,
        color: tuple[float, float, float, float] | None = None,
    ) -> None:
        self.graphics.drawString(int(x), int(y), text)

    def drawNumber(
        self,
        x: float,
        y: float,
        number: float,
        decimals: int = 2,
    ) -> None:
        fmt = f"{{:.{decimals}f}}"
        self.graphics.drawString(int(x), int(y), fmt.format(number))

    def setGraphicsState(
        self,
        fog: int,
        lighting: int,
        alpha: int,
        depth: int,
        depth_write: int,
        cull: int,
    ) -> None:
        # No-op in simless mode
        return None

    def bindTexture2d(self, texture_id: int, unit: int) -> None:
        # No-op in simless mode
        return None

    def generateTextureNumbers(self, count: int) -> List[int]:
        # Dummy texture IDs
        return list(range(1, count + 1))

    def deleteTexture(self, texture_id: int) -> None:
        # No-op in simless mode
        return None

    # ----------------------------------------------------------------------
    # XPLMUtilities
    # ----------------------------------------------------------------------
    def speakString(self, text: str) -> None:
        self._dbg(f"[Speak] {text}")

    def getSystemPath(self) -> str:
        return os.getcwd() + os.sep

    def getPrefsPath(self) -> str:
        return os.getcwd() + os.sep

    def getDirectorySeparator(self) -> str:
        return os.sep
