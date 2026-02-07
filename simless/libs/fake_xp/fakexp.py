# simless/libs/fake_xp/fakexp.py
# ===========================================================================
# FakeXP — unified xp.* façade for simless plugin execution
#
# Thin coordinator that wires together constants, datarefs, widgets, graphics,
# and flightloops into a single XPPython3-compatible xp.* surface.
# ===========================================================================

from __future__ import annotations

import os
from typing import Any, List, Sequence

import XPPython3
from XPPython3.xp_typing import XPLMFlightLoopID, XPWidgetID

from sshd_extensions.xp_interface import XPInterface
from sshd_extensions.fake_xp_interface import FakeXPInterface
from plugins.sshd_extensions.datarefs import DataRefManager, DRefType

from .constants import bind_xp_constants
from .datarefs import DataRefAPI, FakeDataRefInfo
from .widgets import FakeXPWidgets
from .graphics import FakeXPGraphics
from .flightloops import FlightLoopAPI
from simless.libs.fake_xp_runner import FakeXPRunner


class FakeXP(XPInterface, FakeXPInterface):
    def __init__(self, *, debug: bool = False, enable_gui: bool = True) -> None:
        self.debug: bool = debug
        self.enable_gui: bool = enable_gui

        # Core tables / state
        self._runner: FakeXPRunner | None = None
        self._dataref_manager: DataRefManager | None = None
        self._plugins: list[Any] = []
        self._disabled_plugins: set[int] = set()
        self._sim_time: float = 0.0
        self._running: bool = False
        self._keyboard_focus: int | None = None

        # Subsystems
        self.datarefs = DataRefAPI(self)
        self.widgets = FakeXPWidgets(self)
        self.graphics = FakeXPGraphics(self) if enable_gui else None
        self.flightloops = FlightLoopAPI(self)

        # Bind xp.* API
        XPPython3.xp = self
        xp = XPPython3.xp

        # 1. Constants (widget classes, properties, messages, etc.)
        bind_xp_constants(xp)

        # 2. Widget API (methods bound to xp.* and self.*)
        for name in self.widgets.public_api_names:
            fn = getattr(self.widgets, name)
            setattr(xp, name, fn)
            setattr(self, name, fn)

        # 3. Graphics API (only if GUI enabled)
        if self.graphics is not None:
            for name in self.graphics.public_api_names:
                fn = getattr(self.graphics, name)
                setattr(xp, name, fn)
                setattr(self, name, fn)

        # 4. DataRef API
        for name in self.datarefs.public_api_names:
            fn = getattr(self.datarefs, name)
            setattr(xp, name, fn)
            setattr(self, name, fn)

        # 5. FlightLoop API
        for name in self.flightloops.public_api_names:
            fn = getattr(self.flightloops, name)
            setattr(xp, name, fn)
            setattr(self, name, fn)

        # 6. destroyWidget wrapper (XPPython3-style)
        def destroyWidget(self_: FakeXP, wid: XPWidgetID, destroy_children: int = 1) -> None:
            self_.widgets.killWidget(wid)

        xp.destroyWidget = destroyWidget.__get__(self)
        self.destroyWidget = destroyWidget.__get__(self)

    # ----------------------------------------------------------------------
    # Debug helper
    # ----------------------------------------------------------------------
    def _dbg(self, msg: str) -> None:
        if self.debug:
            print(f"[FakeXP] {msg}")

    # ----------------------------------------------------------------------
    # Lifecycle helpers (simless only)
    # ----------------------------------------------------------------------
    def _run_plugin_lifecycle(
        self,
        plugin_names: list[str],
        *,
        run_time: float = -1.0,
    ) -> None:
        runner = FakeXPRunner(
            self,
            run_time=run_time,
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
    # Time
    # ----------------------------------------------------------------------
    def getElapsedTime(self) -> float:
        return self._sim_time

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
        if self.graphics is None:
            return (1920, 1080)
        return self.graphics.getScreenSize()

    def getMouseLocation(self) -> tuple[int, int]:
        if self.graphics is None:
            return (0, 0)
        return self.graphics.getMouseLocation()

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
