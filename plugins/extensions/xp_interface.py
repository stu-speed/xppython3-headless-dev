# ===========================================================================
# FakeXP Interfaces — unified protocol layer for production + simless
#
# Defines the minimal set of interfaces that FakeXP, FakeXPWidgets,
# FakeXPGraphics, and plugin objects must satisfy. These Protocols provide
# a stable, typed contract shared across both real XPPython3 (production)
# and FakeXP (simless) environments.
#
# Responsibilities:
#   • Specify the callable surface expected from each subsystem:
#       - XPWidgetAPI: widget creation, geometry, properties, callbacks
#       - XPGraphicsAPI: draw callbacks and simple primitives
#       - XPUtilitiesAPI: filesystem and utility helpers
#       - XPPluginAPI: plugin lifecycle contract
#   • Enable strong typing and static analysis for plugin authors
#   • Allow FakeXP to emulate X‑Plane behavior without requiring XPLM
#
# Production notes:
#   • These Protocols mirror the structure of XPPython3’s xp.* modules
#   • Plugin code written against these interfaces runs identically in
#     production and simless modes
#
# Simless notes:
#   • FakeXP implements these Protocols directly using pure Python
#   • DearPyGui is used for widget and graphics emulation where applicable
#
# Design goals:
#   • Keep interfaces minimal, explicit, and stable
#   • Avoid leaking implementation details from either environment
#   • Provide a single source of truth for plugin‑facing API contracts
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Protocol, Sequence, Union

from XPPython3.xp_typing import XPLMDataRefInfo_t


class FakeRefInfoProto(Protocol):
    """
    Structural view of FakeXP's FakeRefInfo, without importing FakeXP.
    """

    path: str
    xp_type: int | None
    writable: bool
    is_array: bool
    size: int
    dummy: bool
    value: Any


DataRefHandle = Union[FakeRefInfoProto, XPLMDataRefInfo_t]
DataRefInfo = Union[FakeRefInfoProto, XPLMDataRefInfo_t]


class XPInterface(Protocol):
    # ------------------------------------------------------------------
    # Logging / lifecycle
    # ------------------------------------------------------------------
    def log(self, msg: str) -> None: ...
    def getMyID(self) -> int: ...
    def disablePlugin(self, plugin_id: int) -> None: ...

    # ------------------------------------------------------------------
    # DataRefs
    # ------------------------------------------------------------------
    def add_dataref(
        self,
        path: str,
        default_value: Any,
        writable: bool = False,
    ) -> None: ...

    def findDataRef(self, path: str) -> DataRefHandle | None: ...
    def getDataRefInfo(self, handle: DataRefHandle) -> DataRefInfo: ...

    def getDatai(self, handle: DataRefHandle) -> int: ...
    def getDataf(self, handle: DataRefHandle) -> float: ...
    def getDatad(self, handle: DataRefHandle) -> float: ...
    def getDatavi(self, handle: DataRefHandle) -> list[int]: ...
    def getDatavf(self, handle: DataRefHandle) -> list[float]: ...
    def getDatab(self, handle: DataRefHandle) -> bytes: ...

    def setDatai(self, handle: DataRefHandle, v: int) -> None: ...
    def setDataf(self, handle: DataRefHandle, v: float) -> None: ...
    def setDatad(self, handle: DataRefHandle, v: float) -> None: ...
    def setDatavi(self, handle: DataRefHandle, v: Sequence[int]) -> None: ...
    def setDatavf(self, handle: DataRefHandle, v: Sequence[float]) -> None: ...
    def setDatab(self, handle: DataRefHandle, v: bytes) -> None: ...

    # ------------------------------------------------------------------
    # Flight loops
    # ------------------------------------------------------------------
    def createFlightLoop(self, callback: Callable[..., Any]) -> int: ...
    def scheduleFlightLoop(self, loop_id: int, interval: float) -> None: ...
    def destroyFlightLoop(self, loop_id: int) -> None: ...
    def run_flightloops(self, iterations: int = 5, dt: float = 2.0) -> None: ...

    # ------------------------------------------------------------------
    # XPWidgets
    # ------------------------------------------------------------------
    def createWidget(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        visible: int,
        descriptor: str,
        is_root: int,
        container: int,
        widget_class: int,
    ) -> int: ...

    def createCustomWidget(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        visible: int,
        descriptor: str,
        is_root: int,
        container: int,
        callback: Callable[[int, int, Any, Any], Any],
    ) -> int: ...

    def destroyWidget(self, wid: int, destroy_children: int) -> None: ...

    def setWidgetGeometry(
        self,
        wid: int,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None: ...

    def getWidgetGeometry(self, wid: int) -> tuple[int, int, int, int]: ...

    def showWidget(self, wid: int) -> None: ...
    def hideWidget(self, wid: int) -> None: ...
    def isWidgetVisible(self, wid: int) -> bool: ...

    def getParentWidget(self, wid: int) -> int | None: ...
    def getWidgetWithFocus(self) -> int | None: ...
    def setKeyboardFocus(self, wid: int | None) -> None: ...

    def getWidgetProperty(self, wid: int, prop: int) -> Any: ...
    def setWidgetProperty(self, wid: int, prop: int, value: Any) -> None: ...

    def addWidgetCallback(
        self,
        wid: int,
        callback: Callable[[int, int, Any, Any], Any],
    ) -> None: ...

    def sendWidgetMessage(
        self,
        wid: int,
        msg: int,
        param1: Any = None,
        param2: Any = None,
    ) -> None: ...

    # ImGui-backed rendering
    def begin_frame(self) -> None: ...
    def end_frame(self) -> None: ...
    def render_widgets(self) -> None: ...

    # ------------------------------------------------------------------
    # XPLMGraphics
    # ------------------------------------------------------------------
    def registerDrawCallback(
        self,
        callback: Callable[[int, int, Any], int],
        phase: int,
        before: int,
        refcon: Any,
    ) -> None: ...

    def unregisterDrawCallback(
        self,
        callback: Callable[[int, int, Any], int],
        phase: int,
        before: int,
        refcon: Any,
    ) -> None: ...

    def run_draw_callbacks(self) -> None: ...

    def drawString(
        self,
        x: float,
        y: float,
        text: str,
        color: tuple[float, float, float, float] | None = None,
    ) -> None: ...

    def drawNumber(
        self,
        x: float,
        y: float,
        number: float,
        decimals: int = 2,
    ) -> None: ...

    def setGraphicsState(
        self,
        fog: int,
        lighting: int,
        alpha: int,
        depth: int,
        depth_write: int,
        cull: int,
    ) -> None: ...

    def bindTexture2d(self, texture_id: int, unit: int) -> None: ...
    def generateTextureNumbers(self, count: int) -> list[int]: ...
    def deleteTexture(self, texture_id: int) -> None: ...

    # ------------------------------------------------------------------
    # XPLMUtilities
    # ------------------------------------------------------------------
    def speakString(self, text: str) -> None: ...
    def getSystemPath(self) -> str: ...
    def getPrefsPath(self) -> str: ...
    def getDirectorySeparator(self) -> str: ...
