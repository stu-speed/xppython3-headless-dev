# ===========================================================================
# Fake Interfaces — internal Protocols mirroring the production xp.* API
#
# Defines the lightweight Protocols used by FakeXP to model the callable
# surface of the real XPPython3 xp.* modules. These interfaces mirror the
# production API so plugin code can run unchanged in both real X‑Plane and
# FakeXP’s simless environment.
#
# Responsibilities:
#   • Specify typed contracts for widgets, graphics, datarefs, utilities,
#     and plugin lifecycle behavior
#   • Keep subsystem boundaries explicit and decoupled inside FakeXP
#   • Support static analysis and maintainability without requiring XPLM
#
# Notes:
#   • Protocols reflect the structure and naming of the production xp.* API
#   • FakeXP implements these Protocols directly using pure Python
#   • Implementations (FakeXPWidgets, FakeXPGraphics, etc.) conform to these
#     contracts to ensure consistent behavior across environments
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Protocol, Tuple


# ---------------------------------------------------------------------------
# Common type aliases
# ---------------------------------------------------------------------------

WidgetHandle = int
WidgetCallback = Callable[[int, int, Any, Any], Any]
ColorRGBA = Tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# XPWidgetAPI
# ---------------------------------------------------------------------------

class XPWidgetAPI(Protocol):
    """
    Interface for the widget subsystem used by FakeXP.

    Implementations are expected to manage an internal widget registry and
    provide X-Plane-like widget operations backed by DearPyGui or another
    GUI toolkit.
    """

    _widgets: dict[WidgetHandle, Any]

    # Creation / destruction
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
    ) -> WidgetHandle: ...

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
        callback: WidgetCallback,
    ) -> WidgetHandle: ...

    def killWidget(self, wid: WidgetHandle) -> None: ...

    # Geometry
    def setWidgetGeometry(
        self,
        wid: WidgetHandle,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> None: ...

    def getWidgetGeometry(self, wid: WidgetHandle) -> tuple[int, int, int, int]: ...
    def getWidgetExposedGeometry(self, wid: WidgetHandle) -> tuple[int, int, int, int]: ...

    # Visibility / stacking
    def showWidget(self, wid: WidgetHandle) -> None: ...
    def hideWidget(self, wid: WidgetHandle) -> None: ...
    def isWidgetVisible(self, wid: WidgetHandle) -> bool: ...
    def isWidgetInFront(self, wid: WidgetHandle) -> bool: ...
    def bringWidgetToFront(self, wid: WidgetHandle) -> None: ...
    def pushWidgetBehind(self, wid: WidgetHandle) -> None: ...

    # Hierarchy / class
    def getParentWidget(self, wid: WidgetHandle) -> WidgetHandle | None: ...
    def getWidgetClass(self, wid: WidgetHandle) -> int: ...
    def getWidgetUnderlyingWindow(self, wid: WidgetHandle) -> int: ...

    # Descriptor
    def setWidgetDescriptor(self, wid: WidgetHandle, desc: str) -> None: ...
    def getWidgetDescriptor(self, wid: WidgetHandle) -> str: ...

    # Hit testing / focus
    def getWidgetForLocation(self, x: int, y: int) -> WidgetHandle | None: ...
    def setKeyboardFocus(self, wid: WidgetHandle | None) -> None: ...
    def loseKeyboardFocus(self) -> None: ...

    # Properties
    def setWidgetProperty(self, wid: WidgetHandle, prop: int, value: Any) -> None: ...
    def getWidgetProperty(self, wid: WidgetHandle, prop: int) -> Any: ...

    # Callbacks / messaging
    def addWidgetCallback(self, wid: WidgetHandle, callback: WidgetCallback) -> None: ...
    def sendWidgetMessage(
        self,
        wid: WidgetHandle,
        msg: int,
        param1: Any = None,
        param2: Any = None,
    ) -> None: ...

    # Rendering hook (DearPyGui-backed)
    def _draw_all_widgets(self) -> None: ...


# ---------------------------------------------------------------------------
# XPGraphicsAPI
# ---------------------------------------------------------------------------

class XPGraphicsAPI(Protocol):
    """
    Interface for the graphics subsystem used by FakeXP.

    Implementations provide a simple drawing surface and a callback
    mechanism for plugins to render overlays or HUDs.
    """

    def registerDrawCallback(self, callback: Callable[[], None]) -> None: ...
    def run_draw_callbacks(self) -> None: ...

    def drawString(self, x: int, y: int, text: str) -> None: ...
    def drawNumber(self, x: int, y: int, number: float) -> None: ...

    def drawLine(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: ColorRGBA = (255, 255, 255, 255),
    ) -> None: ...

    def drawRect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        color: ColorRGBA = (255, 255, 255, 255),
    ) -> None: ...

    def drawCircle(
        self,
        x: int,
        y: int,
        radius: int,
        color: ColorRGBA = (255, 255, 255, 255),
    ) -> None: ...


# ---------------------------------------------------------------------------
# XPUtilitiesAPI
# ---------------------------------------------------------------------------

class XPUtilitiesAPI(Protocol):
    """
    Interface for the utilities subsystem used by FakeXP.

    Provides minimal filesystem and user-feedback helpers that mirror
    XPLMUtilities behavior where needed.
    """

    def speakString(self, text: str) -> None: ...
    def getSystemPath(self) -> str: ...
    def getPrefsPath(self) -> str: ...
    def getDirectorySeparator(self) -> str: ...


# ---------------------------------------------------------------------------
# XPPluginAPI
# ---------------------------------------------------------------------------

class XPPluginAPI(Protocol):
    """
    Interface that all FakeXP plugins are expected to implement.

    This mirrors the XPPython3 plugin lifecycle, with return types chosen
    to match typical X-Plane conventions.
    """

    def XPluginStart(self) -> Any: ...
    def XPluginEnable(self) -> int: ...
    def XPluginDisable(self) -> None: ...
    def XPluginStop(self) -> None: ...
