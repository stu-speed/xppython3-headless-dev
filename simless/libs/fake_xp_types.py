# simless/libs/fake_xp_types.py

from __future__ import annotations

from dataclasses import dataclass, field
from enum import auto, StrEnum
from typing import Any, Callable, Dict, List, Optional, Tuple

from PythonPlugins.sshd_extensions.dataref_manager import DRefType
from XPPython3.xp_typing import (
    XPLMCursorStatus, XPLMMouseStatus, XPLMWindowDecoration, XPLMWindowID, XPLMWindowLayer,
    XPWidgetClass, XPWidgetID, XPWidgetPropertyID
)

# XPLM data type bitmask constants
Type_Unknown = 0
Type_Int = 1
Type_Float = 2
Type_Double = 4
Type_FloatArray = 8
Type_IntArray = 16
Type_Data = 32

XPWidgetCallback = Callable[[int, int, Any, Any], int]

# XP12-style struct dictionary
FlightLoopStruct = Dict[str, Any]


class XPShutdown(Exception):
    """Raised when DearPyGui is no longer running (viewport closed)."""
    pass


@dataclass(slots=True)
class FakeDataRef:
    """
    In-memory representation of an X-Plane-style DataRef.

    A FakeDataRef progresses through multiple authority phases over its lifetime.
    Type and shape authority are established independently and may arrive in
    different orders (e.g., META before UPDATE).

    Fields:
      path:
        Fully-qualified DataRef path (e.g. "sim/flightmodel/position/latitude").

      type:
        Declared numeric storage type for the DataRef. This reflects the
        authoritative numeric type once `type_known` is True.

      writable:
        Whether the DataRef is writable by plugins once type authority is known.

      size:
        Storage size of the DataRef. Meaningful only when `shape_known` is True.
        Scalars use size == 1; arrays use size == element count.

      value:
        Current stored value. Prior to shape promotion, this may contain
        provisional (dummy) data written by plugins.

      is_array:
        Shape indicator once known.
          • None  → shape not yet known
          • False → scalar DataRef
          • True  → array DataRef
        This field MUST NOT be consulted unless `shape_known` is True.

      type_known:
        Indicates that authoritative type metadata has been received (META).
        When False, the DataRef's numeric type is provisional.

      shape_known:
        Indicates that authoritative shape information has been established
        from a real provider value (UPDATE). When False, scalar vs array and
        size are unknown and must not be inferred.
    """
    path: str
    type: DRefType
    writable: bool
    size: int
    value: Any
    is_array: bool | None = None
    type_known: bool = False
    shape_known: bool = False

    @property
    def is_dummy(self) -> bool:
        return not self.type_known or not self.shape_known


@dataclass(slots=True)
class WidgetInfo:
    """
    Authoritative record for a single XPWidget.

    GEOMETRY DOMAINS
    ----------------

    1. XP GEOMETRY (authoritative)
       geometry = (left, top, right, bottom)
       • XP‑semantic rectangle.
       • Local to the WindowEx client area.
       • Origin at top-left, Y increases downward.
       • This is what plugins read/write.

    2. DPG CONTAINER GEOMETRY (derived)
       container_geom_applied = (lx, ly, width, height)
       • Geometry last applied to the DPG child_window.
       • Derived from XP geometry + parent XP geometry.
       • Used to enforce “apply exactly once”.

    3. DPG WINDOW GEOMETRY (derived)
       geom_applied = bool
       • Whether the DPG window/control geometry has been applied.

    BACKEND OBJECTS
    ---------------
    dpg_id:
        The DPG item representing the actual control (text, button, slider, etc.)

    container_id:
        The DPG child_window used for absolute positioning.
        All controls live inside this container.

    These backend handles are created by _ensure_dpg_item_for_widget()
    and destroyed by killWidget() or destroyWindow().
    """

    # XP identity and hierarchy
    wid: XPWidgetID
    widget_class: XPWidgetClass
    geometry: Tuple[int, int, int, int]  # XP geometry

    parent: Optional[XPWidgetID] = None
    children: list[XPWidgetID] = field(default_factory=list)
    descriptor: str = ""
    visible: bool = True

    # Backend handles (DPG)
    dpg_id: Optional[str] = None
    container_id: Optional[str] = None

    # DPG geometry state
    geom_applied: bool = False
    container_geom_applied: Optional[Tuple[int, int, int, int]] = None

    # XPWidget properties and callbacks
    properties: Dict[XPWidgetPropertyID, Any] = field(default_factory=dict)
    callbacks: List[XPWidgetCallback] = field(default_factory=list)

    # Interaction state
    edit_buffer: Optional[str] = None

    # XP geometry helpers
    @property
    def left(self) -> int: return self.geometry[0]

    @property
    def top(self) -> int: return self.geometry[1]

    @property
    def right(self) -> int: return self.geometry[2]

    @property
    def bottom(self) -> int: return self.geometry[3]

    @property
    def width(self) -> int: return max(0, self.right - self.left)

    @property
    def height(self) -> int: return max(0, self.bottom - self.top)


@dataclass(slots=True)
class WindowExInfo:
    """
    Graphics-owned representation of an XPLM WindowEx window.

    This is NOT a widget and does not participate in XPWidgets directly.
    It owns a retained-mode widget tree that is rendered inside this window.
    """

    # ------------------------------------------------------------------
    # XP-visible identity and geometry
    # ------------------------------------------------------------------
    wid: XPLMWindowID
    frame: Tuple[int, int, int, int]
    client: Tuple[int, int, int, int]

    visible: bool
    decoration: XPLMWindowDecoration
    layer: XPLMWindowLayer

    # ------------------------------------------------------------------
    # XP callback hooks (verbatim, no wrapping)
    # ------------------------------------------------------------------
    draw_cb: Optional[Callable[[XPLMWindowID, Any], None]]
    click_cb: Optional[
        Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
    ]
    right_click_cb: Optional[
        Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
    ]
    key_cb: Optional[
        Callable[[XPLMWindowID, int, int, int, Any, int], int]
    ]
    cursor_cb: Optional[
        Callable[[XPLMWindowID, int, int, Any], XPLMCursorStatus]
    ]
    wheel_cb: Optional[
        Callable[[XPLMWindowID, int, int, int, int, Any], int]
    ]
    refcon: Any

    # ------------------------------------------------------------------
    # Graphics backend ownership (DearPyGui)
    # ------------------------------------------------------------------
    dpg_window_id: int | str
    drawlist_id: int | str

    # ------------------------------------------------------------------
    # XP ↔ DPG geometry state
    # ------------------------------------------------------------------
    dirty_xp_to_dpg: bool = True
    dirty_dpg_to_xp: bool = False

    # ------------------------------------------------------------------
    # Widget tree (retained-mode UI inside this WindowEx)
    # ------------------------------------------------------------------
    widget_root: Optional[XPWidgetID] = None
    widgets: Dict[XPWidgetID, WidgetInfo] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Frame geometry helpers
    # ------------------------------------------------------------------
    @property
    def left(self) -> int: return self.frame[0]

    @property
    def top(self) -> int: return self.frame[1]

    @property
    def right(self) -> int: return self.frame[2]

    @property
    def bottom(self) -> int: return self.frame[3]

    @property
    def width(self) -> int: return self.right - self.left

    @property
    def height(self) -> int: return self.top - self.bottom

    def hit_test_frame(self, xp_x: int, xp_y: int) -> bool:
        return (
            self.left <= xp_x <= self.right
            and self.bottom <= xp_y <= self.top
        )

    # ------------------------------------------------------------------
    # Client geometry helpers
    # ------------------------------------------------------------------
    @property
    def client_left(self) -> int: return self.client[0]

    @property
    def client_top(self) -> int: return self.client[1]

    @property
    def client_right(self) -> int: return self.client[2]

    @property
    def client_bottom(self) -> int: return self.client[3]

    def hit_test_client(self, xp_x: int, xp_y: int) -> bool:
        return (
            self.client_left <= xp_x <= self.client_right
            and self.client_bottom <= xp_y <= self.client_top
        )

    # ------------------------------------------------------------------
    # XP → DPG transforms (window‑local)
    # ------------------------------------------------------------------
    def xp_to_window_dpg(self, xp_x: int, xp_y: int) -> tuple[int, int]:
        """Convert XP screen coords to DPG coords local to this window."""
        dpg_x = xp_x - self.left
        dpg_y = self.top - xp_y
        return dpg_x, dpg_y


class EventKind(StrEnum):
    MOUSE_BUTTON = "mouse_button"
    MOUSE_WHEEL = "mouse_wheel"
    CURSOR = "cursor"
    KEY = "key"


@dataclass(slots=True)
class EventInfo:
    """Normalized input event with explicit XP coordinates.

    XP semantics are authoritative.
    Backend coordinates may be provided only for normalization.
    """

    # ------------------------------------------------------------------
    # Event identity
    # ------------------------------------------------------------------
    kind: EventKind

    # ------------------------------------------------------------------
    # XP screen-space coordinates (authoritative)
    #
    # Origin: bottom-left
    # Y increases upward
    # ------------------------------------------------------------------
    xp_x: Optional[int] = None
    xp_y: Optional[int] = None

    # ------------------------------------------------------------------
    # Mouse button
    # ------------------------------------------------------------------
    state: Optional[str] = None  # "down" | "up"
    button: Optional[int] = None
    right: bool = False

    # ------------------------------------------------------------------
    # Mouse wheel
    # ------------------------------------------------------------------
    wheel: Optional[int] = None
    clicks: Optional[int] = None

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    key: Optional[int] = None
    flags: Optional[int] = None
    vKey: Optional[int] = None

    # ------------------------------------------------------------------
    # Backend passthrough (unused by XP semantics)
    # ------------------------------------------------------------------
    user_data: Any = None

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------
    @classmethod
    def from_xp(
        cls,
        *,
        kind: EventKind,
        xp_x: Optional[int] = None,
        xp_y: Optional[int] = None,
        **kwargs,
    ) -> "EventInfo":
        """Create an EventInfo with explicit XP coordinates."""
        return cls(kind=kind, xp_x=xp_x, xp_y=xp_y, **kwargs)

    @classmethod
    def from_dpg(
        cls,
        *,
        kind: EventKind,
        dpg_x: int,
        dpg_y: int,
        dpg_vp_height: int,
        **kwargs,
    ) -> "EventInfo":
        """Create an EventInfo from DearPyGui coordinates.

        Converts DPG (top-left origin) to XP (bottom-left origin).
        """
        return cls(
            kind=kind,
            xp_x=int(dpg_x),
            xp_y=int(dpg_vp_height - dpg_y),
            **kwargs,
        )


class DPGOp(StrEnum):
    """Deferred DearPyGui mutation operations."""

    # --------------------------------------------------
    # Drawing
    # --------------------------------------------------
    DRAW_TEXT = auto()
    DRAW_RECTANGLE = auto()

    # --------------------------------------------------
    # Containers / widgets
    # --------------------------------------------------
    ADD_DRAWLIST = auto()
    ADD_WINDOW = auto()
    ADD_CHILD_WINDOW = auto()
    ADD_TEXT = auto()
    ADD_INPUT_TEXT = auto()
    ADD_SLIDER_INT = auto()
    ADD_BUTTON = auto()

    # --------------------------------------------------
    # Item mutation
    # --------------------------------------------------
    CONFIGURE_ITEM = auto()
    SET_VALUE = auto()
    SHOW_ITEM = auto()
    HIDE_ITEM = auto()
    DELETE_ITEM = auto()

    # --------------------------------------------------
    # Menus (XPLMMenus → DearPyGui)
    # --------------------------------------------------
    ADD_MENU_BAR = auto()  # dpg.add_menu_bar()
    ADD_MENU = auto()  # dpg.add_menu()
    ADD_MENU_ITEM = auto()  # dpg.add_menu_item()
    ADD_MENU_SEPARATOR = auto()  # dpg.add_separator()
    SET_MENU_ITEM_CHECKED = auto()  # dpg.configure_item(check=True/False)
    SET_MENU_ITEM_ENABLED = auto()  # dpg.configure_item(enabled=True/False)


@dataclass(frozen=True, slots=True)
class DPGCommand:
    """Deferred DearPyGui operation.

    Recorded during XP callbacks.
    Executed during frame replay only.
    """

    op: DPGOp

    # Routing
    target_drawlist: Optional[int] = None  # None for non-draw ops

    # Positional + keyword arguments for the DPG call
    args: Tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
