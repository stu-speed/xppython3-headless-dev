# ===========================================================================
# XPInterface — typed, minimal API contract for xp.*
#
# This Protocol defines the small, stable subset of the XPPython3 xp.* API
# that shared libraries depend on. It is *not* required by production
# plugins at runtime — XPPython3 provides the real xp module — but it allows
# IDE to type‑check and validate all code that interacts with xp.*.
#
# In short:
#   XPInterface is a design‑time contract. It is not required by production
#   plugins, but it ensures that all library code using xp.* is typed,
#   validated, and portable between real X‑Plane and the simless FakeXP
#   environment.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Protocol, Sequence, Union, runtime_checkable

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


# ======================================================================
# Shared DataRef handle / info types
# ======================================================================

class FakeRefInfoProto(Protocol):
    """
    Minimal shape of FakeXP's FakeDataRefInfo, so code can type against
    a common interface without importing FakeXP internals.
    """
    path: str
    xp_type: int
    writable: bool
    is_array: bool
    size: int
    dummy: bool
    value: Any


DataRefHandle = Union[XPLMDataRef, FakeRefInfoProto, Any]
DataRefInfo = Union[XPLMDataRefInfo_t, FakeRefInfoProto, Any]


# ======================================================================
# Flight loop callback type
# ======================================================================

FlightLoopCallback = Callable[[float, float, int, Any], float]


# ======================================================================
# XPInterface Protocol
# ======================================================================

@runtime_checkable
class XPInterface(Protocol):
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
    # DataRef API (XPLMDataAccess + FakeXP)
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

    # Array get/set — XPPython3-compatible buffer API
    # When out is None and count == 0, return length (int).
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
    # Flight loops (XPLMProcessing / XPPython3 Python API)
    # ------------------------------------------------------------------
    def createFlightLoop(
        self,
        callback: FlightLoopCallback | tuple[int, FlightLoopCallback, Any] | list[Any],
        phase: XPLMFlightLoopPhaseType = XPLMFlightLoopPhaseType(0),
        refCon: Any | None = None,
    ) -> XPLMFlightLoopID: ...
    """
    XPPython3 supports:
        createFlightLoop(callback, phase=0, refCon=None)
        createFlightLoop((phase, callback, refCon))
    FakeXP mirrors this behavior.
    """

    def scheduleFlightLoop(
        self,
        loop_id: XPLMFlightLoopID,
        interval: float,
        relativeToNow: int = 1,
    ) -> None: ...

    def destroyFlightLoop(self, loop_id: XPLMFlightLoopID) -> None: ...

    # ------------------------------------------------------------------
    # Widgets (XPStandardWidgets / FakeXPWidgets)
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
    # Graphics (XPLMGraphics / XPLMDisplay / FakeXPGraphics)
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
    # Utilities (XPLMUtilities subset)
    # ------------------------------------------------------------------
    def getSystemPath(self) -> str: ...
    def getPrefsPath(self) -> str: ...
    def getDirectorySeparator(self) -> str: ...
