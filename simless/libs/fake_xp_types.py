# simless/libs/fake_xp_types.py

from __future__ import annotations

from dataclasses import dataclass, field
from enum import auto, StrEnum
from typing import Any, Callable, Dict, List, Optional, Tuple

from sshd_extensions.dataref_manager import DRefType
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

    Geometry is stored in global XP screen coordinates as:
        (left, top, right, bottom)

    Width and height are always derived; they are never stored.
    """

    # ------------------------------------------------------------------
    # XP authoritative identity and hierarchy
    # ------------------------------------------------------------------
    wid: XPWidgetID
    widget_class: XPWidgetClass
    parent: XPWidgetID  # XPWidgetID(0) for root widgets
    descriptor: str

    # ------------------------------------------------------------------
    # XP authoritative geometry and visibility
    # ------------------------------------------------------------------
    geometry: Tuple[int, int, int, int]  # (left, top, right, bottom)
    visible: bool = True

    # ------------------------------------------------------------------
    # XP widget properties and callbacks
    # ------------------------------------------------------------------
    properties: Dict[XPWidgetPropertyID, Any] = field(default_factory=dict)
    callbacks: List[XPWidgetCallback] = field(default_factory=list)

    # ------------------------------------------------------------------
    # DearPyGui backend handles (opaque to XP layer)
    # ------------------------------------------------------------------
    dpg_id: Optional[int | str] = None
    container_id: Optional[int | str] = None

    # ------------------------------------------------------------------
    # Geometry lifecycle tracking (backend-facing only)
    # ------------------------------------------------------------------
    geom_applied: bool = False
    container_geom_applied: Optional[Tuple[int, int, int, int]] = None

    # ------------------------------------------------------------------
    # Interaction state
    # ------------------------------------------------------------------
    edit_buffer: Optional[str] = None

    # ------------------------------------------------------------------
    # Derived geometry helpers (XP semantics)
    # ------------------------------------------------------------------
    @property
    def left(self) -> int:
        return self.geometry[0]

    @property
    def top(self) -> int:
        return self.geometry[1]

    @property
    def right(self) -> int:
        return self.geometry[2]

    @property
    def bottom(self) -> int:
        return self.geometry[3]

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.top - self.bottom)


@dataclass(slots=True)
class WindowExInfo:
    """
    Graphics-owned representation of an XPLM WindowEx window.

    This is NOT a widget and does not participate in XPWidgets.
    It exists solely to define a drawable region and route callbacks.
    """

    # ------------------------------------------------------------------
    # XP-visible identity and geometry
    # ------------------------------------------------------------------
    wid: XPLMWindowID

    # Desired XP-style frame rectangle (left, top, right, bottom).
    # Always authoritative:
    #   - XP sets it when XP wants to move/resize the window.
    #   - DPG updates it when the user drags/resizes the window.
    #   - XP→DPG apply uses it before render.
    #   - DPG→XP read overwrites it after render.
    #
    # Initialized at window creation to the XP constructor geometry.
    frame: Tuple[int, int, int, int]

    # Desired XP-style client rectangle (left, top, right, bottom).
    # Defaults to the frame rect until the first DPG render produces
    # a real drawlist rect. After that, updated every frame from DPG.
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

    # XP→DPG: set True when XP changes geometry and wants DPG to apply it.
    # Cleared AFTER DPG renders the frame.
    dirty_xp_to_dpg: bool = True

    # DPG→XP: set True when DPG geometry differs from stored XP geometry.
    # Cleared AFTER XP consumes the change.
    dirty_dpg_to_xp: bool = False

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
