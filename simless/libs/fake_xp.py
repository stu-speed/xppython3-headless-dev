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
from typing import Any, Callable, Dict, List, Sequence, Tuple, Optional, Union

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


class ArrayElementHandle:
    def __init__(self, base: str, index: int):
        self.base = base
        self.index = index


@dataclass(slots=True)
class FakeDataRefInfo:
    path: str
    xp_type: int | None
    writable: bool
    is_array: bool
    size: int = 0
    dummy: bool = False
    value: Any = None


class FakeXP:
    def __init__(self, *, debug: bool = False) -> None:
        self.debug_enabled: bool = debug

        # DataRef tables — keyed strictly by path
        self._handles: Dict[str, FakeDataRefInfo] = {}
        self._dummy_refs: Dict[str, FakeDataRefInfo] = {}
        self._values: Dict[str, Any] = {}
        self._datarefs: dict[str, dict] = {}

        # Runner reference (set by FakeXPRunner)
        self._runner: FakeXPRunner | None = None

        # Optional DataRefManager
        self._dataref_manager: DataRefManager | None = None

        # Plugin list (populated by runner)
        self._plugins: List[Any] = []

        # Disabled plugin tracking
        self._disabled_plugins: set[int] = set()

        # Widgets + Graphics
        self.widgets = FakeXPWidgets(self)
        self.graphics = FakeXPGraphics(self)

        # Sim time
        self._sim_time: float = 0.0

        # Loop control
        self._running: bool = False

        # Keyboard focus
        self._keyboard_focus: int | None = None

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

        # Bind widget API to xp.* and to self.*
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

    # ----------------------------------------------------------------------
    # Debug helper
    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if self.debug_enabled:
            print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # Lifecycle helpers
    # ----------------------------------------------------------------------
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
        return 1

    def disablePlugin(self, plugin_id: int) -> None:
        self._disabled_plugins.add(plugin_id)
        self._dbg(f"disablePlugin({plugin_id})")

    def log(self, msg: str) -> None:
        print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # DataRefManager binding
    # ----------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: DataRefManager) -> None:
        self._dataref_manager = mgr

    # ----------------------------------------------------------------------
    # Simless auto-registration
    # ----------------------------------------------------------------------
    def fake_register_dataref(self, path: str, default: Any | None, writable: bool | None) -> FakeDataRefInfo:
        if path in self._handles:
            return self._handles[path]

        is_array = isinstance(default, (list, tuple, bytes, bytearray))
        ref = FakeDataRefInfo(
            path=path,
            xp_type=None,
            writable=bool(writable) if writable is not None else True,
            is_array=is_array,
            size=0,
            dummy=False,
            value=default,
        )

        self._handles[path] = ref
        self._values[path] = default
        self._dbg(f"fake_register_dataref('{path}')")
        return ref

    # ----------------------------------------------------------------------
    # DataRef API
    # ----------------------------------------------------------------------
    def findDataRef(self, name: str):
        # Detect array element syntax: dataref[index]
        if "[" in name and name.endswith("]"):
            base, idx_str = name[:-1].split("[", 1)
            index = int(idx_str)

            # Promote base dataref as array if needed
            if base not in self._datarefs:
                # Default to float array of size 8 (X‑Plane uses fixed sizes)
                self._datarefs[base] = {
                    "type": "float_array",
                    "values": [0.0] * 8,
                }
                self._dbg(f"Promoted '{base}' to real float array")

            return ArrayElementHandle(base, index)

        # Scalar fallback → create uninitialized string dataref
        if name not in self._handles:
            ref = FakeDataRefInfo(
                path=name,
                xp_type=1,  # string dataref
                writable=True,
                is_array=False,
                size=0,
                dummy=True,  # <-- uninitialized
                value="<<<uninitialized>>>",
            )
            self._handles[name] = ref
            self._values[name] = "<<<uninitialized>>>"
            self._dbg(f"Promoted '{name}' to dummy scalar dataref")

        return self._handles[name]

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
        """Convert a dummy ref into a real one."""
        ref.dummy = False
        ref.xp_type = xp_type
        ref.is_array = is_array
        ref.value = default

        # Move from dummy → real
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
        """Ensure a handle is real; promote if needed."""
        if handle.dummy:
            return self._promote(handle, xp_type, is_array, default)
        return handle

    def _resolve_value_ref(
            self,
            handle: Union[FakeDataRefInfo, ArrayElementHandle, str],
    ) -> Tuple[FakeDataRefInfo, Optional[int]]:
        """
        Returns (ref, index) where:
          - ref is a FakeDataRefInfo (never a string)
          - index is None for scalar refs
          - index is an int for array-element refs
        """

        # ------------------------------------------------------------
        # ARRAY ELEMENT
        # ------------------------------------------------------------
        if isinstance(handle, ArrayElementHandle):
            base = handle.base
            index = handle.index

            # Ensure base dataref handle exists
            if base not in self._handles:
                ref = FakeDataRefInfo(
                    path=base,
                    xp_type=16,  # XPLMType_FloatArray
                    writable=True,
                    is_array=True,
                    size=0,
                    dummy=True,
                    value=[],  # float array default
                )
                self._handles[base] = ref
                self._values[base] = []
            else:
                ref = self._handles[base]

            # Promote if needed
            ref = self._ensure_real(
                ref,
                xp_type=16,  # float array
                is_array=True,
                default=[],
            )
            return ref, index

        # ------------------------------------------------------------
        # SCALAR
        # ------------------------------------------------------------
        # Convert scalar handle (string path) → FakeDataRefInfo
        if isinstance(handle, str):
            if handle not in self._handles:
                ref = FakeDataRefInfo(
                    path=handle,
                    xp_type=1,  # XPLMType_Data (string)
                    writable=True,
                    is_array=False,
                    size=0,
                    dummy=True,
                    value="<<<uninitialized>>>",
                )
                self._handles[handle] = ref
                self._values[handle] = "<<<uninitialized>>>"
            else:
                ref = self._handles[handle]
        else:
            # Already a FakeDataRefInfo
            ref = handle

        # Promote if needed
        ref = self._ensure_real(
            ref,
            xp_type=1,  # string dataref
            is_array=False,
            default="<<<uninitialized>>>",
        )
        return ref, None

    # ----------------------------------------------------------------------
    # Datai
    # ----------------------------------------------------------------------
    def getDatai(self, handle):
        ref, idx = self._resolve_value_ref(handle)

        if idx is not None:
            arr = self._values.get(ref.path, ref.value or [])
            return int(arr[idx])

        value = self._values.get(ref.path, ref.value or 0)
        return int(value)

    def setDatai(self, handle, value):
        ref, idx = self._resolve_value_ref(handle)
        v = int(value)

        if idx is not None:
            arr = self._values.setdefault(ref.path, ref.value or [])
            arr[idx] = v
        else:
            ref.value = v
            self._values[ref.path] = v

        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Dataf
    # ----------------------------------------------------------------------
    def getDataf(self, handle):
        ref, idx = self._resolve_value_ref(handle)

        if idx is not None:
            arr = self._values.get(ref.path, ref.value or [])
            return float(arr[idx])

        value = self._values.get(ref.path, ref.value or 0.0)
        return float(value)

    def setDataf(self, handle, value):
        ref, idx = self._resolve_value_ref(handle)
        v = float(value)

        if idx is not None:
            arr = self._values.setdefault(ref.path, ref.value or [])
            arr[idx] = v
        else:
            ref.value = v
            self._values[ref.path] = v

        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datad (double mapped to float)
    # ----------------------------------------------------------------------
    def getDatad(self, handle):
        ref, idx = self._resolve_value_ref(handle)

        if idx is not None:
            arr = self._values.get(ref.path, ref.value or [])
            return float(arr[idx])

        value = self._values.get(ref.path, ref.value or 0.0)
        return float(value)

    def setDatad(self, handle, value):
        ref, idx = self._resolve_value_ref(handle)
        v = float(value)

        if idx is not None:
            arr = self._values.setdefault(ref.path, ref.value or [])
            arr[idx] = v
        else:
            ref.value = v
            self._values[ref.path] = v

        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datavf (float array)
    # ----------------------------------------------------------------------
    def getDatavf(self, handle):
        ref, idx = self._resolve_value_ref(handle)
        arr = self._values.get(ref.path, ref.value or [])

        if idx is not None:
            return [float(arr[idx])]

        return [float(v) for v in arr]

    def setDatavf(self, handle, values):
        ref, idx = self._resolve_value_ref(handle)
        arr = self._values.setdefault(ref.path, ref.value or [])

        if idx is not None:
            arr[idx] = float(values[0])
        else:
            arr[:] = [float(v) for v in values]

        ref.value = arr

        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datavi (int array)
    # ----------------------------------------------------------------------
    def getDatavi(self, handle):
        ref, idx = self._resolve_value_ref(handle)
        arr = self._values.get(ref.path, ref.value or [])

        if idx is not None:
            return [int(arr[idx])]

        return [int(v) for v in arr]

    def setDatavi(self, handle, values):
        ref, idx = self._resolve_value_ref(handle)
        arr = self._values.setdefault(ref.path, ref.value or [])

        if idx is not None:
            arr[idx] = int(values[0])
        else:
            arr[:] = [int(v) for v in values]

        ref.value = arr

        if self._dataref_manager:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Datab (byte array)
    # ----------------------------------------------------------------------
    def getDatab(self, handle):
        ref, idx = self._resolve_value_ref(handle)
        arr = self._values.get(ref.path, ref.value or b"")

        if isinstance(arr, (bytes, bytearray)):
            if idx is not None:
                return bytes([arr[idx]])
            return bytes(arr)

        # fallback: list of ints
        if idx is not None:
            return bytes([arr[idx]])

        return bytes(arr)

    def setDatab(self, handle, values):
        ref, idx = self._resolve_value_ref(handle)

        if isinstance(values, (bytes, bytearray)):
            arr = bytearray(values)
        else:
            arr = bytearray(int(v) & 0xFF for v in values)

        store = self._values.setdefault(ref.path, ref.value or bytearray())

        if idx is not None:
            store[idx] = arr[0]
        else:
            store[:] = arr

        ref.value = store

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
    # FlightLoop API
    # ----------------------------------------------------------------------
    def registerFlightLoopCallback(self, cb: Callable, interval: float) -> None:
        if self._runner is None:
            raise RuntimeError("No FakeXPRunner attached")
        self._runner.register_legacy_flightloop(1, cb, interval)

    def createFlightLoop(self, params: Dict[str, Any]) -> Any:
        if self._runner is None:
            raise RuntimeError("No FakeXPRunner attached")
        return self._runner.create_modern_flightloop(1, params)

    def scheduleFlightLoop(self, handle: Any, interval: float, relative: int) -> None:
        if self._runner is None:
            raise RuntimeError("No FakeXPRunner attached")
        self._runner.schedule_modern_flightloop(handle, interval, relative)

    # ----------------------------------------------------------------------
    # Graphics API
    # ----------------------------------------------------------------------
    def registerDrawCallback(self, cb: Callable, phase: int, wantsBefore: int) -> None:
        self.graphics.registerDrawCallback(cb, phase, wantsBefore)

    def unregisterDrawCallback(self, cb: Callable, phase: int, wantsBefore: int) -> None:
        self.graphics.unregisterDrawCallback(cb, phase, wantsBefore)

    def drawString(self, color: Sequence[float], x: int, y: int, text: str, wordWrapWidth: int) -> None:
        self.graphics.drawString(color, x, y, text, wordWrapWidth)

    def drawNumber(self, color: Sequence[float], x: int, y: int, number: float, digits: int, decimals: int) -> None:
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

    def setKeyboardFocus(self, widget_id: int) -> None:
        self._keyboard_focus = widget_id
        self._dbg(f"Keyboard focus → {widget_id}")

    def loseKeyboardFocus(self, widget_id: int) -> None:
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
    def createMenu(self, *args, **kwargs):
        self._dbg("createMenu() called — stub")
        return 1

    def appendMenuItem(self, *args, **kwargs):
        self._dbg("appendMenuItem() called — stub")

    def appendMenuSeparator(self, *args, **kwargs):
        self._dbg("appendMenuSeparator() called — stub")

    def setMenuItemName(self, *args, **kwargs):
        self._dbg("setMenuItemName() called — stub")

    def getMenuItemName(self, *args, **kwargs):
        self._dbg("getMenuItemName() called — stub")
        return ""

    def getMenuItemInfo(self, *args, **kwargs):
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
    def registerHotKey(self, *args, **kwargs):
        self._dbg("registerHotKey() → stub")
        return 1

    def unregisterHotKey(self, *args, **kwargs):
        self._dbg("unregisterHotKey() → stub")

    # ----------------------------------------------------------------------
    # Misc stubs
    # ----------------------------------------------------------------------
    def getVirtualKeyDescription(self, vkey: int) -> str:
        return f"Key {vkey}"

    def getMouseState(self) -> tuple[int, int]:
        return self.graphics.getMouseState()

    def getDatabLength(self, handle: FakeDataRefInfo) -> int:
        ref = self._ensure_real(handle, xp_type=32, is_array=True, default=b"")
        arr = self._values.get(ref.path, ref.value or b"")
        return len(arr)

    def getDatavfLength(self, handle: FakeDataRefInfo) -> int:
        ref = self._ensure_real(handle, xp_type=8, is_array=True, default=[])
        arr = self._values.get(ref.path, ref.value or [])
        return len(arr)

    def getDataviLength(self, handle: FakeDataRefInfo) -> int:
        ref = self._ensure_real(handle, xp_type=16, is_array=True, default=[])
        arr = self._values.get(ref.path, ref.value or [])
        return len(arr)

    # ----------------------------------------------------------------------
    # Plugin enable/disable
    # ----------------------------------------------------------------------
    def isPluginEnabled(self, plugin_id: int) -> bool:
        return plugin_id not in self._disabled_plugins

    def enablePlugin(self, plugin_id: int) -> None:
        if plugin_id in self._disabled_plugins:
            self._disabled_plugins.remove(plugin_id)
        self._dbg(f"enablePlugin({plugin_id})")

    # ----------------------------------------------------------------------
    # Message stubs
    # ----------------------------------------------------------------------
    def sendMessageToPlugin(self, plugin_id: int, msg: int, param: Any) -> None:
        self._dbg(f"sendMessageToPlugin({plugin_id}, {msg}, {param}) → stub")

    # ----------------------------------------------------------------------
    # Cursor stubs
    # ----------------------------------------------------------------------
    def setCursor(self, cursor_type: int) -> None:
        self._dbg(f"setCursor({cursor_type}) → stub")

    # ----------------------------------------------------------------------
    # Drawing phases
    # ----------------------------------------------------------------------
    def getCycleNumber(self) -> int:
        return int(self._sim_time * 60)

    # ----------------------------------------------------------------------
    # Misc xp.* compatibility helpers
    # ----------------------------------------------------------------------
    def getPluginID(self) -> int:
        return 1

    def getNthPlugin(self, index: int) -> int:
        return 1

    def getPluginName(self, plugin_id: int) -> str:
        return "FakeXP"

    def getPluginSignature(self, plugin_id: int) -> str:
        return "fake.xp"

    def getPluginDescription(self, plugin_id: int) -> str:
        return "Simless FakeXP Environment"

    # ----------------------------------------------------------------------
    # Path helpers
    # ----------------------------------------------------------------------
    def getSystemDirectory(self) -> str:
        return os.getcwd()

    def getPrefsDirectory(self) -> str:
        return os.getcwd()

    def getPluginDirectory(self) -> str:
        return os.getcwd()

    # ----------------------------------------------------------------------
    # Sound stubs
    # ----------------------------------------------------------------------
    def playSound(self, sound_id: int) -> None:
        self._dbg(f"playSound({sound_id}) → stub")

    # ----------------------------------------------------------------------
    # Clipboard stubs
    # ----------------------------------------------------------------------
    def getClipboardText(self) -> str:
        self._dbg("getClipboardText() → stub")
        return ""

    def setClipboardText(self, text: str) -> None:
        self._dbg(f"setClipboardText('{text}') → stub")

    # ----------------------------------------------------------------------
    # Joystick stubs
    # ----------------------------------------------------------------------
    def countJoystickButtons(self) -> int:
        return 0

    def getJoystickButtonAssignment(self, button: int) -> tuple[str, str]:
        return ("", "")

    def setJoystickButtonAssignment(self, button: int, desc: str, cmd: str) -> None:
        self._dbg(f"setJoystickButtonAssignment({button}, '{desc}', '{cmd}') → stub")

    # ----------------------------------------------------------------------
    # Mouse stubs
    # ----------------------------------------------------------------------
    def getMouseWheel(self) -> int:
        return 0

    def setMouseWheel(self, delta: int) -> None:
        self._dbg(f"setMouseWheel({delta}) → stub")

    # ----------------------------------------------------------------------
    # DataRef change notifications
    # ----------------------------------------------------------------------
    def _notify_dataref_changed(self, ref: FakeDataRefInfo) -> None:
        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Runner attachment
    # ----------------------------------------------------------------------
    def _attach_runner(self, runner: FakeXPRunner) -> None:
        self._runner = runner

    # ----------------------------------------------------------------------
    # Sim time update (called by runner)
    # ----------------------------------------------------------------------
    def _update_sim_time(self, dt: float) -> None:
        self._sim_time += dt

    # ----------------------------------------------------------------------
    # Plugin loading helpers
    # ----------------------------------------------------------------------
    def _load_plugins(self, plugin_names: list[str]) -> None:
        self._plugins = plugin_names

    def getNthPluginInfo(self, index: int) -> tuple[str, str, str, str]:
        return ("FakeXP", "1.0", "fake.xp", "Simless FakeXP Environment")

    # ----------------------------------------------------------------------
    # Logging helpers
    # ----------------------------------------------------------------------
    def debugString(self, msg: str) -> None:
        self._dbg(msg)

    # ----------------------------------------------------------------------
    # Menu click stub
    # ----------------------------------------------------------------------
    def handleMenuClick(self, menu_id: int, item: int) -> None:
        self._dbg(f"handleMenuClick({menu_id}, {item}) → stub")

    # ----------------------------------------------------------------------
    # Cursor visibility stubs
    # ----------------------------------------------------------------------
    def hideCursor(self) -> None:
        self._dbg("hideCursor() → stub")

    def showCursor(self) -> None:
        self._dbg("showCursor() → stub")

    # ----------------------------------------------------------------------
    # DataRef type queries
    # ----------------------------------------------------------------------
    def getDataRefTypes(self, handle: FakeDataRefInfo) -> int:
        if handle.dummy:
            return 0
        return handle.xp_type or 0

    # ----------------------------------------------------------------------
    # DataRef writable query
    # ----------------------------------------------------------------------
    def canWriteDataRef(self, handle: FakeDataRefInfo) -> bool:
        return bool(handle.writable)

    # ----------------------------------------------------------------------
    # DataRef existence helpers
    # ----------------------------------------------------------------------
    def dataRefExists(self, path: str) -> bool:
        return path in self._handles or path in self._dummy_refs

    # ----------------------------------------------------------------------
    # DataRef value helpers
    # ----------------------------------------------------------------------
    def getDataRefValue(self, path: str) -> Any:
        ref = self.findDataRef(path)
        if ref is None:
            return None
        return self._values.get(ref.path, ref.value)

    def setDataRefValue(self, path: str, value: Any) -> None:
        ref = self.findDataRef(path)
        if ref is None:
            return

        # Determine type
        if isinstance(value, float):
            self.setDataf(ref, value)
        elif isinstance(value, int):
            self.setDatai(ref, value)
        elif isinstance(value, (bytes, bytearray)):
            self.setDatab(ref, value)
        elif isinstance(value, Sequence):
            # Heuristic: float array if any float present
            if any(isinstance(v, float) for v in value):
                self.setDatavf(ref, value)
            else:
                self.setDatavi(ref, value)
        else:
            # Fallback: store raw
            ref = self._ensure_real(ref, xp_type=0, is_array=False, default=value)
            ref.value = value
            self._values[ref.path] = value

        if self._dataref_manager is not None:
            self._dataref_manager._notify_dataref_changed(ref)

    # ----------------------------------------------------------------------
    # Plugin reload stub
    # ----------------------------------------------------------------------
    def reloadPlugin(self, plugin_id: int) -> None:
        self._dbg(f"reloadPlugin({plugin_id}) → stub")

    # ----------------------------------------------------------------------
    # Command creation stub
    # ----------------------------------------------------------------------
    def createCommand(self, name: str, description: str) -> int:
        self._dbg(f"createCommand('{name}', '{description}') → stub")
        return 1

    # ----------------------------------------------------------------------
    # Command handler stubs
    # ----------------------------------------------------------------------
    def registerCommandHandler(self, cmd: int, handler: Callable, before: int, refcon: Any) -> None:
        self._dbg(f"registerCommandHandler({cmd}) → stub")

    def unregisterCommandHandler(self, cmd: int, handler: Callable, before: int, refcon: Any) -> None:
        self._dbg(f"unregisterCommandHandler({cmd}) → stub")

    # ----------------------------------------------------------------------
    # Cursor state stubs
    # ----------------------------------------------------------------------
    def getCursorPosition(self) -> tuple[int, int]:
        return self.graphics.getMouseLocation()

    # ----------------------------------------------------------------------
    # Window stubs
    # ----------------------------------------------------------------------
    def createWindow(self, *args, **kwargs):
        self._dbg("createWindow() → stub")
        return 1

    def destroyWindow(self, win_id: int) -> None:
        self._dbg(f"destroyWindow({win_id}) → stub")

    def setWindowTitle(self, win_id: int, title: str) -> None:
        self._dbg(f"setWindowTitle({win_id}, '{title}') → stub")

    def getWindowGeometry(self, win_id: int) -> tuple[int, int, int, int]:
        return (0, 0, 100, 100)

    def setWindowGeometry(self, win_id: int, left: int, top: int, right: int, bottom: int) -> None:
        self._dbg(f"setWindowGeometry({win_id}, {left}, {top}, {right}, {bottom}) → stub")

    # ----------------------------------------------------------------------
    # Window visibility stubs
    # ----------------------------------------------------------------------
    def isWindowVisible(self, win_id: int) -> bool:
        return True

    def setWindowVisible(self, win_id: int, visible: int) -> None:
        self._dbg(f"setWindowVisible({win_id}, {visible}) → stub")

    # ----------------------------------------------------------------------
    # Deprecated drawing stubs
    # ----------------------------------------------------------------------
    def drawTranslucentDarkBox(self, left: int, top: int, right: int, bottom: int) -> None:
        self._dbg(f"drawTranslucentDarkBox({left}, {top}, {right}, {bottom}) → stub")

    # ----------------------------------------------------------------------
    # Map stubs
    # ----------------------------------------------------------------------
    def createMapLayer(self, *args, **kwargs):
        self._dbg("createMapLayer() → stub")
        return 1

    def registerMapCreationHook(self, *args, **kwargs):
        self._dbg("registerMapCreationHook() → stub")

    # ----------------------------------------------------------------------
    # VR stubs
    # ----------------------------------------------------------------------
    def isVREnabled(self) -> bool:
        return False

