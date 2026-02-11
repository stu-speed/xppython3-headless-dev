# stubs/simless/libs/simless_xp_interface.pyi
# ===========================================================================
# SimlessXPInterface — typed, minimal API contract for xp.* in simless mode
#
# PURPOSE
#   Defines the production‑safe xp.* API surface that FakeXP must implement.
#   This Protocol exists solely for strong typing, IDE support, and
#   architectural clarity during simless development.
#
# CONTRACT REQUIREMENT
#   SimlessXPInterface MUST match the real XPPython3 xp.* contract EXACTLY
#   as defined in the production xp.pyi file.
#
#   • No simless‑only helpers may appear here.
#   • No additional parameters, overloads, or behaviors may be added.
#   • No methods may be removed or renamed.
#   • Signatures, return types, and semantics must remain identical.
#
# RELATIONSHIP TO FakeXPInterface
#   FakeXPInterface extends this Protocol with simless‑only helpers such as
#   fake_register_dataref() and bind_dataref_manager(). Those extensions MUST
#   NOT appear here, and production plugins MUST NEVER see them.
#
# PRODUCTION SAFETY
#   Production plugins NEVER import this file. They import the real
#   XPPython3 xp.* module. This file is strictly for simless development,
#   FakeXP implementation, DataRefManager, and test harnesses.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Protocol, Sequence, runtime_checkable
from dataclasses import dataclass

from XPPython3.xp_typing import (
    XPLMDataRef,
    XPLMDataRefInfo_t,
    XPLMFlightLoopID,
    XPLMFlightLoopPhaseType,
    XPLMDrawingPhase,
    XPLMTextureID,
    XPLMWindowID,
    XPWidgetID,
    XPWidgetClass,
    XPWidgetMessage,
    XPWidgetPropertyID,
)


# ===========================================================================
# Simless-only DataRef metadata (used when FakeXP auto-generates DataRefs)
# ===========================================================================
@dataclass(slots=True)
class FakeRefInfo:
    path: str
    xp_type: int
    writable: bool
    is_array: bool
    size: int
    dummy: bool
    value: Any


# ===========================================================================
# DataRef handle / info types
# ===========================================================================
DataRefHandle = XPLMDataRef | FakeRefInfo
DataRefInfo = XPLMDataRefInfo_t | FakeRefInfo


# ===========================================================================
# Flight loop callback type (XP11 legacy signature)
# ===========================================================================
FlightLoopCallback = Callable[[float, float, int, Any], float]


# ===========================================================================
# SimlessXPInterface Protocol
# ===========================================================================
@runtime_checkable
class SimlessXPInterface(Protocol):
    # ------------------------------------------------------------------
    # Logging / lifecycle
    # ------------------------------------------------------------------
    def log(self, msg: str) -> None: ...
    def getMyID(self) -> int: ...
    def disablePlugin(self, plugin_id: int) -> None: ...

    # ------------------------------------------------------------------
    # Time / processing
    # ------------------------------------------------------------------
    def getElapsedTime(self) -> float: ...

    # ------------------------------------------------------------------
    # DataRef API (real XPPython3 contract)
    # ------------------------------------------------------------------
    def findDataRef(self, name: str) -> DataRefHandle | None: ...
    def getDataRefInfo(self, handle: DataRefHandle) -> DataRefInfo | None: ...

    # Scalar get/set
    def getDatai(self, handle: DataRefHandle) -> int: ...
    def setDatai(self, handle: DataRefHandle, value: int) -> None: ...

    def getDataf(self, handle: DataRefHandle) -> float: ...
    def setDataf(self, handle: DataRefHandle, value: float) -> None: ...

    def getDatad(self, handle: DataRefHandle) -> float: ...
    def setDatad(self, handle: DataRefHandle, value: float) -> None: ...

    # Array get/set
    def getDatavf(
        self,
        handle: DataRefHandle,
        out: Sequence[float] | None,
        offset: int,
        count: int,
    ) -> int | None: ...

    def setDatavf(
        self,
        handle: DataRefHandle,
        values: Sequence[float],
        offset: int,
        count: int,
    ) -> None: ...

    def getDatavi(
        self,
        handle: DataRefHandle,
        out: Sequence[int] | None,
        offset: int,
        count: int,
    ) -> int | None: ...

    def setDatavi(
        self,
        handle: DataRefHandle,
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None: ...

    def getDatab(
        self,
        handle: DataRefHandle,
        out: bytearray | None,
        offset: int,
        count: int,
    ) -> int | None: ...

    def setDatab(
        self,
        handle: DataRefHandle,
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None: ...

    # ------------------------------------------------------------------
    # Flight loops (XP11 legacy signature)
    # ------------------------------------------------------------------
    def createFlightLoop(
        self,
        callback: FlightLoopCallback
        | tuple[int, FlightLoopCallback, Any]
        | list[Any],
        phase: XPLMFlightLoopPhaseType = XPLMFlightLoopPhaseType(0),
        refCon: Any | None = None,
    ) -> XPLMFlightLoopID: ...

    def scheduleFlightLoop(
        self,
        loop_id: XPLMFlightLoopID,
        interval: float,
        relativeToNow: int = 1,
    ) -> None: ...

    def destroyFlightLoop(self, loop_id: XPLMFlightLoopID) -> None: ...

    # ------------------------------------------------------------------
    # Widgets
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
        container: XPWidgetID,
        widget_class: XPWidgetClass,
    ) -> XPWidgetID: ...

    def killWidget(self, wid: XPWidgetID) -> None: ...
    def destroyWidget(self, wid: XPWidgetID, destroy_children: int = 1) -> None: ...

    def setWidgetGeometry(
        self,
        wid: XPWidgetID,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None: ...

    def getWidgetGeometry(self, wid: XPWidgetID) -> tuple[int, int, int, int]: ...
    def getWidgetExposedGeometry(self, wid: XPWidgetID) -> tuple[int, int, int, int]: ...

    def showWidget(self, wid: XPWidgetID) -> None: ...
    def hideWidget(self, wid: XPWidgetID) -> None: ...
    def isWidgetVisible(self, wid: XPWidgetID) -> bool: ...
    def isWidgetInFront(self, wid: XPWidgetID) -> bool: ...
    def bringWidgetToFront(self, wid: XPWidgetID) -> None: ...
    def pushWidgetBehind(self, wid: XPWidgetID) -> None: ...

    def getParentWidget(self, wid: XPWidgetID) -> XPWidgetID | None: ...
    def getWidgetClass(self, wid: XPWidgetID) -> XPWidgetClass: ...
    def getWidgetUnderlyingWindow(self, wid: XPWidgetID) -> XPLMWindowID | None: ...

    def setWidgetDescriptor(self, wid: XPWidgetID, desc: str) -> None: ...
    def getWidgetDescriptor(self, wid: XPWidgetID) -> str: ...

    def getWidgetForLocation(
        self,
        x: int,
        y: int,
        in_front: int,
    ) -> XPWidgetID | None: ...

    def setKeyboardFocus(self, wid: XPWidgetID | None) -> None: ...
    def loseKeyboardFocus(self, wid: XPWidgetID) -> None: ...

    def setWidgetProperty(
        self,
        wid: XPWidgetID,
        prop: XPWidgetPropertyID,
        value: Any,
    ) -> None: ...

    def getWidgetProperty(
        self,
        wid: XPWidgetID,
        prop: XPWidgetPropertyID,
    ) -> Any: ...

    def addWidgetCallback(
        self,
        wid: XPWidgetID,
        callback: Callable[[XPWidgetMessage, XPWidgetID, Any, Any], Any],
    ) -> None: ...

    def sendWidgetMessage(
        self,
        wid: XPWidgetID,
        msg: XPWidgetMessage,
        param1: Any | None = None,
        param2: Any | None = None,
    ) -> None: ...

    # ------------------------------------------------------------------
    # Graphics
    # ------------------------------------------------------------------
    def registerDrawCallback(
        self,
        callback: Callable[[XPLMDrawingPhase, int, Any], int],
        phase: XPLMDrawingPhase,
        wantsBefore: int,
    ) -> None: ...

    def unregisterDrawCallback(
        self,
        callback: Callable[[XPLMDrawingPhase, int, Any], int],
        phase: XPLMDrawingPhase,
        wantsBefore: int,
    ) -> None: ...

    def drawString(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        text: str,
        wordWrapWidth: int,
    ) -> None: ...

    def drawNumber(
        self,
        color: Sequence[float],
        x: int,
        y: int,
        number: float,
        digits: int,
        decimals: int,
    ) -> None: ...

    def setGraphicsState(
        self,
        fog: int,
        lighting: int,
        alpha: int,
        smooth: int,
        texUnits: int,
        texMode: int,
        depth: int,
    ) -> None: ...

    def bindTexture2d(self, textureID: XPLMTextureID, unit: int) -> None: ...
    def generateTextureNumbers(self, count: int) -> list[XPLMTextureID]: ...
    def deleteTexture(self, textureID: XPLMTextureID) -> None: ...

    # ------------------------------------------------------------------
    # Screen / mouse
    # ------------------------------------------------------------------
    def getScreenSize(self) -> tuple[int, int]: ...
    def getMouseLocation(self) -> tuple[int, int]: ...

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def getSystemPath(self) -> str: ...
    def getPrefsPath(self) -> str: ...
    def getDirectorySeparator(self) -> str: ...
