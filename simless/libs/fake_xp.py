# ===========================================================================
# FakeXP — unified xp.* façade for simless plugin execution
#
# Provides a complete, in‑memory implementation of the xp.* API surface used
# by XPPython3 plugins. FakeXP acts as the central coordinator for all simless
# subsystems: DataRefs, Widgets, Graphics, and Utilities.
# ===========================================================================

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence

import XPPython3
from XPPython3.xp_typing import XPLMFlightLoopID, XPWidgetID

from sshd_extensions.xp_interface import XPInterface
from sshd_extensions.fake_xp_interface import FakeXPInterface
from plugins.sshd_extensions.datarefs import DataRefManager, DRefType
from simless.libs.fake_xp_runner import FakeXPRunner
from simless.libs.fake_xp_widget import FakeXPWidgets
from simless.libs.fake_xp_graphics import FakeXPGraphics


class ArrayElementHandle:
    def __init__(self, base: str, index: int) -> None:
        self.base = base
        self.index = index


@dataclass(slots=True)
class FakeDataRefInfo:
    """
    Minimal X-Plane-style dataref descriptor for FakeXP.
    xp_type:
      1 = float
      2 = int
      3 = float array
      4 = int array
      5 = byte array
    """
    path: str
    xp_type: int
    writable: bool
    is_array: bool
    size: int
    dummy: bool
    value: Any

    def __repr__(self) -> str:
        kind = "array" if self.is_array else "scalar"
        dummy = " dummy" if self.dummy else ""
        return f"<FakeDataRefInfo {self.path} ({kind}, type={self.xp_type}, size={self.size}{dummy})>"


class FakeXP(XPInterface, FakeXPInterface):
    def __init__(self, *, debug: bool = False, enable_gui: bool = True) -> None:
        self.debug_enabled = debug
        self.enable_gui = enable_gui

        # DataRef tables
        self._handles = {}
        self._dummy_refs = {}
        self._values = {}
        self._datarefs = {}

        self._runner = None
        self._dataref_manager = None
        self._plugins = []
        self._disabled_plugins = set()

        # Widgets always available
        self.widgets = FakeXPWidgets(self)

        # Graphics only if GUI enabled
        self.graphics = FakeXPGraphics(self) if enable_gui else None

        # Sim time
        self._sim_time = 0.0
        self._running = False
        self._keyboard_focus = None

        # Bind xp.* API
        XPPython3.xp = self
        xp = XPPython3.xp

        # 1. Widget class constants (public API, simless-safe values)
        xp.WidgetClass_MainWindow = 1
        xp.WidgetClass_SubWindow = 2
        xp.WidgetClass_Button = 3
        xp.WidgetClass_TextField = 4
        xp.WidgetClass_Caption = 5
        xp.WidgetClass_ScrollBar = 6
        xp.WidgetClass_GeneralGraphics = 7

        # 2. Widget properties (public API)
        # Scrollbars
        xp.Property_ScrollBarMin = 100
        xp.Property_ScrollBarMax = 101
        xp.Property_ScrollBarSliderPosition = 102
        xp.Property_ScrollBarPageAmount = 103
        xp.Property_ScrollBarType = 104
        xp.ScrollBarTypeScrollBar = 0
        xp.ScrollBarTypeSlider = 1

        # Main window properties
        xp.Property_MainWindowHasCloseBoxes = 110

        # Buttons
        xp.Property_ButtonType = 200
        xp.PushButton = 0
        xp.RadioButton = 1
        xp.CheckBox = 2

        # 3. Widget messages (public API)
        xp.Msg_MouseDown = 1
        xp.Msg_MouseDrag = 2
        xp.Msg_MouseUp = 3
        xp.Msg_KeyPress = 4
        xp.Msg_ScrollBarSliderPositionChanged = 5
        xp.Msg_PushButtonPressed = 6
        xp.Message_CloseButtonPushed = 7

        # 4. Bind FakeXPWidgets methods to xp.* and self.*
        widget_api = [
            "createWidget", "killWidget", "setWidgetGeometry", "getWidgetGeometry",
            "getWidgetExposedGeometry", "showWidget", "hideWidget", "isWidgetVisible",
            "isWidgetInFront", "bringWidgetToFront", "pushWidgetBehind",
            "getParentWidget", "getWidgetClass", "getWidgetUnderlyingWindow",
            "setWidgetDescriptor", "getWidgetDescriptor", "getWidgetForLocation",
            "setKeyboardFocus", "loseKeyboardFocus", "setWidgetProperty",
            "getWidgetProperty", "addWidgetCallback", "sendWidgetMessage",
        ]

        for name in widget_api:
            fn = getattr(self.widgets, name)
            setattr(xp, name, fn)
            setattr(self, name, fn)

        # 5. Public destroyWidget wrapper (XPPython3 API)
        def destroyWidget(self_: FakeXP, wid: XPWidgetID, destroy_children: int = 1) -> None:
            self_.widgets.killWidget(wid)

        xp.destroyWidget = destroyWidget.__get__(self)
        self.destroyWidget = destroyWidget.__get__(self)

    # ----------------------------------------------------------------------
    # Debug helper
    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if self.debug_enabled:
            print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # Lifecycle helpers (simless only)
    # ----------------------------------------------------------------------
    def _run_plugin_lifecycle(
        self,
        plugin_names: list[str],
        *,
        debug: bool = False,
        enable_gui: bool = True,
        run_time: float = -1.0,
    ) -> None:
        runner = FakeXPRunner(
            self,
            enable_gui=self.enable_gui,
            run_time=run_time,
            debug=debug,
        )
        self._runner = runner
        runner.run_plugin_lifecycle(plugin_names)

    def _quit(self) -> None:
        if self._runner is not None:
            self._runner.end_run_loop()

    # ----------------------------------------------------------------------
    # Base xp methods
    # ----------------------------------------------------------------------
    def getMyID(self) -> int:
        return 1

    def disablePlugin(self, plugin_id: int) -> None:
        self._disabled_plugins.add(plugin_id)
        self._dbg(f"disablePlugin({plugin_id})")

    def log(self, msg: str) -> None:
        print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # DataRefManager binding (simless only)
    # ----------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: DataRefManager) -> None:
        self._dataref_manager = mgr
        self._dbg("[DataRef] DataRefManager bound to FakeXP")

    # ----------------------------------------------------------------------
    # Simless auto-registration
    # ----------------------------------------------------------------------
    def fake_register_dataref(
        self,
        path: str,
        *,
        xp_type: int,
        is_array: bool = False,
        size: int = 1,
        writable: bool = True,
    ) -> FakeDataRefInfo:
        dtype = DRefType(xp_type)

        if dtype == DRefType.FLOAT_ARRAY:
            value: Any = [0.0] * size
        elif dtype == DRefType.INT_ARRAY:
            value = [0] * size
        elif dtype == DRefType.BYTE_ARRAY:
            value = bytearray(size)
        elif dtype == DRefType.FLOAT:
            value = 0.0
        elif dtype == DRefType.INT:
            value = 0
        elif dtype == DRefType.DOUBLE:
            value = 0.0
        else:
            raise TypeError(f"Unsupported dtype {dtype} for {path}")

        ref = FakeDataRefInfo(
            path=path,
            xp_type=int(dtype),
            writable=writable,
            is_array=is_array,
            size=size,
            dummy=False,
            value=value,
        )

        self._handles[path] = ref
        self._values[path] = value
        self._dbg(f"fake_register_dataref('{path}', type={int(dtype)}, array={is_array}, size={size})")
        return ref

    # ----------------------------------------------------------------------
    # DataRef API
    # ----------------------------------------------------------------------
    def findDataRef(self, name: str) -> FakeDataRefInfo | None:
        if "[" in name or "]" in name:
            self._dbg(f"findDataRef rejected invalid array element syntax: '{name}'")
            return None

        if name in self._handles:
            return self._handles[name]

        if name in self._datarefs:
            ref_dict = self._datarefs[name]
            return ref_dict.get("handle")  # type: ignore[return-value]

        is_array = name.endswith("s") or "array" in name.lower()

        if is_array:
            dtype = DRefType.FLOAT_ARRAY
            value: Any = [0.0] * 8
            size = 8
            self._dbg(f"Promoted '{name}' to dummy float array dataref")
        else:
            dtype = DRefType.FLOAT
            value = 0.0
            size = 1
            self._dbg(f"Promoted '{name}' to dummy scalar dataref")

        ref = FakeDataRefInfo(
            path=name,
            xp_type=int(dtype),
            writable=True,
            is_array=is_array,
            size=size,
            dummy=True,
            value=value,
        )

        self._handles[name] = ref
        self._values[name] = value
        return ref

    def getDataRefInfo(self, handle: FakeDataRefInfo) -> FakeDataRefInfo:
        return handle

    # ----------------------------------------------------------------------
    # Promotion helpers
    # ----------------------------------------------------------------------
    def _promote(
        self,
        ref: FakeDataRefInfo,
        xp_type: int,
        is_array: bool,
        default: Any,
    ) -> FakeDataRefInfo:
        ref.dummy = False
        ref.xp_type = xp_type
        ref.is_array = is_array
        ref.value = default

        self._dummy_refs.pop(ref.path, None)
        self._handles[ref.path] = ref
        self._values[ref.path] = default

        self._dbg(f"Promoted '{ref.path}' to real dataref")

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

    def _resolve_value_ref(
        self,
        handle: FakeDataRefInfo | str | ArrayElementHandle,
    ) -> tuple[FakeDataRefInfo | None, None]:
        if isinstance(handle, ArrayElementHandle):
            self._dbg(f"Invalid array element handle: {handle.base}[{handle.index}]")
            return None, None

        if isinstance(handle, str):
            ref = self._handles.get(handle)
            if ref is None:
                ref = FakeDataRefInfo(
                    path=handle,
                    xp_type=1,
                    writable=True,
                    is_array=False,
                    size=1,
                    dummy=True,
                    value=0.0,
                )
                self._handles[handle] = ref
                self._values[handle] = 0.0
            return ref, None

        return handle, None

    # ----------------------------------------------------------------------
    # Datai
    # ----------------------------------------------------------------------
    def getDatai(self, handle: FakeDataRefInfo | str) -> int:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None
        return int(self._values.get(ref.path, ref.value))

    def setDatai(self, handle: FakeDataRefInfo | str, value: int) -> None:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None
        v = int(value)
        self._values[ref.path] = v
        ref.value = v
        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Dataf
    # ----------------------------------------------------------------------
    def getDataf(self, handle: FakeDataRefInfo | str) -> float:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None
        return float(self._values.get(ref.path, ref.value))

    def setDataf(self, handle: FakeDataRefInfo | str, value: float) -> None:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None
        v = float(value)
        self._values[ref.path] = v
        ref.value = v
        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datad (double mapped to float)
    # ----------------------------------------------------------------------
    def getDatad(self, handle: FakeDataRefInfo | str) -> float:
        return self.getDataf(handle)

    def setDatad(self, handle: FakeDataRefInfo | str, value: float) -> None:
        self.setDataf(handle, value)

    # ----------------------------------------------------------------------
    # Datavf (float array)
    # ----------------------------------------------------------------------
    def getDatavf(
        self,
        handle: FakeDataRefInfo | str,
        out: List[float] | None,
        offset: int,
        count: int,
    ) -> int | None:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None

        arr = self._values.get(ref.path, ref.value)
        if out is None:
            return len(arr)

        for i in range(count):
            out[i] = float(arr[offset + i])
        return None

    def setDatavf(
        self,
        handle: FakeDataRefInfo | str,
        values: Sequence[float],
        offset: int,
        count: int,
    ) -> None:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None

        arr = self._values.setdefault(ref.path, ref.value or [])
        end = offset + count
        if end > len(arr):
            arr.extend([0.0] * (end - len(arr)))

        for i in range(count):
            arr[offset + i] = float(values[i])

        ref.value = arr
        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datvi (int array)
    # ----------------------------------------------------------------------
    def getDatvi(
        self,
        handle: FakeDataRefInfo | str,
        out: List[int] | None,
        offset: int,
        count: int,
    ) -> int | None:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None
        arr = self._values.get(ref.path, ref.value)
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = int(arr[offset + i])
        return None

    def setDatvi(
        self,
        handle: FakeDataRefInfo | str,
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None
        arr = self._values.setdefault(ref.path, ref.value or [])
        end = offset + count
        if end > len(arr):
            arr.extend([0] * (end - len(arr)))

        for i in range(count):
            arr[offset + i] = int(values[i])

        ref.value = arr
        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datab (byte array)
    # ----------------------------------------------------------------------
    def getDatab(
        self,
        handle: FakeDataRefInfo | str,
        out: bytearray | None,
        offset: int,
        count: int,
    ) -> int | None:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None
        arr: bytearray = self._values.get(ref.path, ref.value)
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = arr[offset + i]
        return None

    def setDatab(
        self,
        handle: FakeDataRefInfo | str,
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None:
        ref, _ = self._resolve_value_ref(handle)
        assert ref is not None
        arr: bytearray = self._values.setdefault(ref.path, ref.value or bytearray())
        end = offset + count
        if end > len(arr):
            arr.extend([0] * (end - len(arr)))

        for i in range(count):
            arr[offset + i] = int(values[i]) & 0xFF

        ref.value = arr
        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # registerDataRef
    # ----------------------------------------------------------------------
    def registerDataRef(
        self,
        path: str,
        xpType: int,
        isArray: bool,
        writable: bool,
        defaultValue: Any,
    ) -> FakeDataRefInfo:
        if path in self._handles:
            return self._handles[path]

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
        self._values[path] = defaultValue
        self._dbg(f"registerDataRef('{path}')")

        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

        return ref

    # ----------------------------------------------------------------------
    # Time
    # ----------------------------------------------------------------------
    def getElapsedTime(self) -> float:
        return self._sim_time

    # ----------------------------------------------------------------------
    # Flight loop API — XPPython3-style createFlightLoop
    # ----------------------------------------------------------------------
    def createFlightLoop(
        self,
        callback_or_tuple: Callable[[float, float, int, Any], float] | Sequence[Any],
        phase: int = 0,
        refCon: Any | None = None,
    ) -> XPLMFlightLoopID:
        if isinstance(callback_or_tuple, (list, tuple)):
            if len(callback_or_tuple) != 3:
                raise TypeError("FlightLoop tuple must be (phase, callback, refCon)")
            phase, cb, refCon = callback_or_tuple
            if not callable(cb):
                raise TypeError("FlightLoop callback must be callable")
        else:
            cb = callback_or_tuple
            if not callable(cb):
                raise TypeError("First argument to createFlightLoop must be a callback")

        if self._runner is None:
            raise RuntimeError("FakeXP runner not initialized before createFlightLoop")

        struct = {
            "structSize": 1,
            "phase": int(phase),
            "callback": cb,
            "refcon": refCon,
        }

        fl_id_int = self._runner.create_flightloop(1, struct)
        return XPLMFlightLoopID(fl_id_int)

    def scheduleFlightLoop(
        self,
        loop_id: XPLMFlightLoopID,
        interval_seconds: float,
    ) -> None:
        if self._runner is None:
            raise RuntimeError("FakeXP runner not initialized before scheduleFlightLoop")
        self._runner.schedule_flightloop(int(loop_id), float(interval_seconds))

    def destroyFlightLoop(self, loop_id: XPLMFlightLoopID) -> None:
        if self._runner is None:
            raise RuntimeError("FakeXP runner not initialized before destroyFlightLoop")
        self._runner.destroy_flightloop(int(loop_id))

    # ----------------------------------------------------------------------
    # Graphics API
    # ----------------------------------------------------------------------
    def registerDrawCallback(self, cb: Callable, phase: int, wantsBefore: int) -> None:
        self.graphics.registerDrawCallback(cb, phase, wantsBefore)

    def unregisterDrawCallback(self, cb: Callable, phase: int, wantsBefore: int) -> None:
        self.graphics.unregisterDrawCallback(cb, phase, wantsBefore)

    def drawString(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        text: str,
        wordWrapWidth: int,
    ) -> None:
        self.graphics.drawString(color, x, y, text, wordWrapWidth)

    def drawNumber(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        number: float,
        digits: int,
        decimals: int,
    ) -> None:
        self.graphics.drawNumber(color, x, y, number, digits, decimals)

    def setGraphicsState(
        self,
        fog: int,
        lighting: int,
        alpha: int,
        smooth: int,
        texUnits: int,
        texMode: int,
        depth: int,
    ) -> None:
        self.graphics.setGraphicsState(fog, lighting, alpha, smooth, texUnits, texMode, depth)

    def bindTexture2d(self, textureID: int, unit: int) -> None:
        self.graphics.bindTexture2d(textureID, unit)

    def generateTextureNumbers(self, count: int) -> List[int]:
        return self.graphics.generateTextureNumbers(count)

    def deleteTexture(self, textureID: int) -> None:
        self.graphics.deleteTexture(textureID)

    # ----------------------------------------------------------------------
    # Keyboard focus
    # ----------------------------------------------------------------------
    def getKeyboardFocus(self) -> int | None:
        return self._keyboard_focus

    def setKeyboardFocus(self, widget_id: XPWidgetID) -> None:
        self._keyboard_focus = widget_id
        self._dbg(f"Keyboard focus → {widget_id}")

    def loseKeyboardFocus(self, widget_id: XPWidgetID) -> None:
        if self._keyboard_focus == widget_id:
            self._keyboard_focus = None
            self._dbg("Keyboard focus cleared")

    # ----------------------------------------------------------------------
    # Window / screen geometry
    # ----------------------------------------------------------------------
    def getScreenSize(self) -> tuple[int, int]:
        return self.graphics.getScreenSize()

    def getMouseLocation(self) -> tuple[int, int]:
        return self.graphics.getMouseLocation()

    # ----------------------------------------------------------------------
    # Menu stubs (not implemented)
    # ----------------------------------------------------------------------
    def createMenu(self, *args: Any, **kwargs: Any) -> int:
        self._dbg("createMenu() called — stub")
        return 1

    def appendMenuItem(self, *args: Any, **kwargs: Any) -> None:
        self._dbg("appendMenuItem() called — stub")

    def appendMenuSeparator(self, *args: Any, **kwargs: Any) -> None:
        self._dbg("appendMenuSeparator() called — stub")

    def setMenuItemName(self, *args: Any, **kwargs: Any) -> None:
        self._dbg("setMenuItemName() called — stub")

    def getMenuItemName(self, *args: Any, **kwargs: Any) -> str:
        self._dbg("getMenuItemName() called — stub")
        return ""

    def getMenuItemInfo(self, *args: Any, **kwargs: Any) -> Any:
        self._dbg("getMenuItemInfo() called — stub")
        return None

    # ----------------------------------------------------------------------
    # Utilities
    # ----------------------------------------------------------------------
    def getDirectorySeparator(self) -> str:
        return os.sep

    def getSystemPath(self) -> str:
        return os.getcwd()

    def getPrefsPath(self) -> str:
        return os.getcwd()

    def getPluginPrefsPath(self) -> str:
        return os.getcwd()

    def getPluginInfo(self, plugin_id: int) -> tuple[str, str, str, str]:
        return ("Fake Plugin", "1.0", "FakeXP", "Simless")

    # ----------------------------------------------------------------------
    # Command stubs
    # ----------------------------------------------------------------------
    def findCommand(self, name: str) -> int:
        self._dbg(f"findCommand('{name}') → stub")
        return 1

    def commandOnce(self, cmd: int) -> None:
        self._dbg(f"commandOnce({cmd}) → stub")

    def commandBegin(self, cmd: int) -> None:
        self._dbg(f"commandBegin({cmd}) → stub")

    def commandEnd(self, cmd: int) -> None:
        self._dbg(f"commandEnd({cmd}) → stub")

    # ----------------------------------------------------------------------
    # Hotkey stubs
    # ----------------------------------------------------------------------
    def registerHotKey(self, *args: Any, **kwargs: Any) -> int:
        self._dbg("registerHotKey() called — stub")
        return 1

    def unregisterHotKey(self, hotkey_id: int) -> None:
        self._dbg(f"unregisterHotKey({hotkey_id}) called — stub")
