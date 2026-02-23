# simless/libs/simless_xp_interface.pyi
# ===========================================================================
# SimlessXPInterface — typed, minimal API contract for xp.* in simless mode
#
# PURPOSE
#   Defines the subset of xp.* API surface that FakeXP can make available.
#   This Protocol exists solely for strong typing, IDE support, and
#   architectural clarity during simless development.
#
# NOTE (special): Because this runtime is a fake/test harness, the Protocol
#   below also exposes a small set of simless-only helper methods that are
#   implemented by FakeXP. These helpers are intended for test harnesses,
#   runners, and the bridge. Production plugins MUST NOT rely on these
#   helpers; they exist only to make testing and promotion of dummy
#   datarefs straightforward.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Protocol, Sequence, runtime_checkable, Optional

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

# Import the FakeDataRef handle type so the Simless type union reflects the
# actual handle objects returned by FakeXP.findDataRef/registerDataAccessor.
# This import is for typing only and does not add production-only API surface.
from simless.libs.fake_xp_dataref import FakeDataRef  # type: ignore


# ===========================================================================
# DataRef handle / info types
# ===========================================================================
# DataRefHandle and DataRefInfo reflect the production XPLM types OR the
# FakeDataRef handle used by the simless FakeXP implementation.
DataRefHandle = XPLMDataRef | FakeDataRef
DataRefInfo = XPLMDataRefInfo_t | FakeDataRef


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
    # NOTE: Signatures mirror production: findDataRef accepts a string and
    # returns an opaque handle; all other accessors accept the handle only.
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

    # ------------------------------------------------------------------
    # Simless-only helpers (FakeXP test/runner utilities)
    # ------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: Any) -> None: ...
    def update_dummy_ref(
        self,
        dataRef: FakeDataRef,
        *,
        dtype: Any | None = None,
        size: int | None = None,
        value: Any | None = None,
    ) -> None: ...
    def promote_handle_by_handle(
        self,
        dataRef: FakeDataRef,
        *,
        dtype: Any,
        is_array: bool,
        size: int,
        writable: bool,
        default_value: Any | None = None,
        preserve_dummy_writes: bool = True,
    ) -> bool: ...
    def attach_handle_callback(self, cb: Optional[Callable[[FakeDataRef], None]]) -> None: ...
    def detach_handle_callback(self) -> None: ...
    def list_handles(self) -> list[str]: ...
    def clear_handles(self) -> None: ...
