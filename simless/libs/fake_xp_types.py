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


class XPShutdown(Exception):
    """Raised when DearPyGui is no longer running (viewport closed)."""
    pass


class FakeXPCommandRef:
    """Opaque, hashable command reference object."""

    def __init__(self, path: str) -> None:
        self.path = path

    def __repr__(self) -> str:
        return f"<FakeXPCommandRef {self.path}>"

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeXPCommandRef) and other.path == self.path


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

    GEOMETRY (authoritative XP domain)
    ----------------------------------
    geometry = (left, top, right, bottom)
    • XP‑semantic rectangle.
    • Local to the WindowEx client area.
    • Origin at top-left, Y increases downward.
    • Plugins read/write this through XP APIs.

    BACK‑REFERENCES
    ---------------
    window:
        The owning WindowExInfo. Required so that any widget mutation
        automatically dirties the window for XP→DPG sync.

    BACKEND OBJECTS (DPG)
    ---------------------
    dpg_id:
        The DPG item representing the actual control (text, button, etc.)
    container_id:
        The DPG child_window used for absolute positioning.

    DPG GEOMETRY STATE
    ------------------
    geom_applied:
        Whether the DPG control geometry has been applied.
    container_geom_applied:
        Last applied geometry for the DPG container.
    """

    # Identity
    wid: XPWidgetID
    widget_class: XPWidgetClass
    window: "WindowExInfo"  # back-reference to owning window

    # Authoritative XP geometry
    _geometry: Tuple[int, int, int, int]

    # Hierarchy
    parent: Optional[XPWidgetID] = None
    children: list[XPWidgetID] = field(default_factory=list)

    # XPWidget state
    _descriptor: str = ""
    _visible: bool = True

    # Backend handles
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

    # ------------------------------------------------------------
    # PROTECTED SETTERS (all mutations dirty the owning WindowEx)
    # ------------------------------------------------------------

    @property
    def geometry(self) -> Tuple[int, int, int, int]:
        return self._geometry

    @geometry.setter
    def geometry(self, value: Tuple[int, int, int, int]):
        self._geometry = value
        self.geom_applied = False
        self.container_geom_applied = None
        self.window.dirty_xp_to_dpg = True

    @property
    def descriptor(self) -> str:
        return self._descriptor

    @descriptor.setter
    def descriptor(self, value: str):
        self._descriptor = value
        self.geom_applied = False
        self.window.dirty_xp_to_dpg = True

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool):
        self._visible = value
        self.geom_applied = False
        self.window.dirty_xp_to_dpg = True

    # ------------------------------------------------------------
    # CHILD MANAGEMENT (must dirty window)
    # ------------------------------------------------------------

    def add_child(self, child_id: XPWidgetID):
        self.children.append(child_id)
        self.window.dirty_xp_to_dpg = True

    def remove_child(self, child_id: XPWidgetID):
        if child_id in self.children:
            self.children.remove(child_id)
            self.window.dirty_xp_to_dpg = True

    # ------------------------------------------------------------
    # PROPERTY MANAGEMENT (must dirty window)
    # ------------------------------------------------------------

    def set_property(self, prop: XPWidgetPropertyID, value: Any):
        self.properties[prop] = value
        self.geom_applied = False
        self.window.dirty_xp_to_dpg = True

    # ------------------------------------------------------------
    # DERIVED GEOMETRY HELPERS (read‑only)
    # ------------------------------------------------------------

    @property
    def left(self) -> int:
        return self._geometry[0]

    @property
    def top(self) -> int:
        return self._geometry[1]

    @property
    def right(self) -> int:
        return self._geometry[2]

    @property
    def bottom(self) -> int:
        return self._geometry[3]

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(slots=True)
class WindowExInfo:
    """
    Graphics-owned representation of an XPLM WindowEx window.

    This object is the *authoritative XP-side model* of a WindowEx.
    It stores XP geometry, XP state, callbacks, and the DearPyGui
    backend IDs used to render the window.

    ------------------------------------------------------------------
    GEOMETRY AUTHORITY MODEL
    ------------------------------------------------------------------

    XP and DPG both modify window geometry, but only one side is
    authoritative at a time.

    • XP-originated changes (XPLMSetWindowGeometry, visibility,
      decoration, layer changes) must push XP → DPG.
      These use:
          set_frame_from_xp()
          set_client_from_xp()

      These setters flip dirty_xp_to_dpg so the next frame applies
      XP geometry to the DPG window.

    • DPG-originated changes (user dragging/resizing the DPG window)
      must update XP’s authoritative geometry model. These updates
      always use:
          set_frame_from_dpg()
          set_client_from_dpg()

      These setters update the XP-side _frame and _client rectangles
      and flip dirty_dpg_to_xp so XP can consume the new geometry on
      the next frame. They intentionally do NOT flip dirty_xp_to_dpg,
      ensuring XP→DPG sync does not override the user’s drag.

    The public properties .frame and .client are read-only views of
    the authoritative XP geometry. They DO NOT flip dirty flags.
    """

    # ------------------------------------------------------------------
    # XP identity
    # ------------------------------------------------------------------
    wid: XPLMWindowID | int

    # Authoritative XP geometry (screen-space)
    _frame: Tuple[int, int, int, int]
    _client: Tuple[int, int, int, int]

    # XP state
    _visible: bool
    _decoration: XPLMWindowDecoration
    _layer: XPLMWindowLayer | int

    # XP callback hooks
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

    # Backend (DearPyGui)
    dpg_window_id: int | str
    drawlist_id: int | str

    # Dirty flags
    dirty_xp_to_dpg: bool = True  # XP changed → must push to DPG
    dirty_dpg_to_xp: bool = False  # DPG changed → must notify XP

    # Widget tree
    widget_root: Optional[XPWidgetID] = None
    widgets: Dict[XPWidgetID, "WidgetInfo"] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Public read-only geometry properties
    # ------------------------------------------------------------------

    @property
    def frame(self) -> Tuple[int, int, int, int]:
        """Authoritative XP frame rect (left, top, right, bottom)."""
        return self._frame

    @property
    def client(self) -> Tuple[int, int, int, int]:
        """Authoritative XP client rect (left, top, right, bottom)."""
        return self._client

    # ------------------------------------------------------------------
    # XP-originated geometry setters (XP → DPG)
    # ------------------------------------------------------------------

    def set_frame_from_xp(self, value: Tuple[int, int, int, int]) -> None:
        """
        XP-originated geometry change.

        XP is authoritative → mark dirty_xp_to_dpg so the next frame
        pushes XP geometry into DPG.
        """
        self._frame = value
        self.dirty_xp_to_dpg = True

    def set_client_from_xp(self, value: Tuple[int, int, int, int]) -> None:
        """
        XP-originated client rect change.

        XP is authoritative → mark dirty_xp_to_dpg so the next frame
        pushes XP client rect into DPG.
        """
        self._client = value
        self.dirty_xp_to_dpg = True

    # ------------------------------------------------------------------
    # DPG-originated geometry setters (DPG → XP)
    # ------------------------------------------------------------------

    def set_frame_from_dpg(self, value: Tuple[int, int, int, int]) -> None:
        """
        DPG-originated geometry change (drag/resize).

        DPG is authoritative → update XP geometry WITHOUT marking
        dirty_xp_to_dpg. This prevents XP→DPG from snapping the
        window back to its old position.

        We DO mark dirty_dpg_to_xp so XP can consume the change.
        """
        self._frame = value
        self.dirty_dpg_to_xp = True

    def set_client_from_dpg(self, value: Tuple[int, int, int, int]) -> None:
        """
        DPG-originated client rect change.

        Same rules as set_frame_from_dpg(): update XP geometry but do
        NOT trigger XP→DPG sync.
        """
        self._client = value
        self.dirty_dpg_to_xp = True

    # ------------------------------------------------------------------
    # XP state setters (these DO push XP → DPG)
    # ------------------------------------------------------------------

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool):
        """
        XP visibility change → XP is authoritative.
        """
        self._visible = value
        self.dirty_xp_to_dpg = True

    @property
    def decoration(self) -> XPLMWindowDecoration:
        return self._decoration

    @decoration.setter
    def decoration(self, value: XPLMWindowDecoration):
        """
        XP decoration change → XP is authoritative.
        """
        self._decoration = value
        self.dirty_xp_to_dpg = True

    @property
    def layer(self) -> XPLMWindowLayer | int:
        return self._layer

    @layer.setter
    def layer(self, value: XPLMWindowLayer):
        """
        XP layer change → XP is authoritative.
        """
        self._layer = value
        self.dirty_xp_to_dpg = True

    # ------------------------------------------------------------------
    # Derived geometry helpers
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

    def frame_contains(self, xp_x: int, xp_y: int) -> bool:
        """Return True if XP coords fall inside the frame rect."""
        return (
            self.left <= xp_x <= self.right
            and self.bottom <= xp_y <= self.top
        )

    @property
    def client_left(self) -> int: return self.client[0]

    @property
    def client_top(self) -> int: return self.client[1]

    @property
    def client_right(self) -> int: return self.client[2]

    @property
    def client_bottom(self) -> int: return self.client[3]

    def client_contains(self, xp_x: int, xp_y: int) -> bool:
        """Return True if XP coords fall inside the client rect."""
        return (
            self.client_left <= xp_x <= self.client_right
            and self.client_bottom <= xp_y <= self.client_top
        )

    # ------------------------------------------------------------------
    # XP → DPG transforms (window‑local)
    # ------------------------------------------------------------------
    def xp_to_window_dpg(self, xp_x: int, xp_y: int) -> tuple[int, int]:
        """
        Convert XP screen coords to DPG coords local to this window.

        XP origin: top-left
        DPG origin: bottom-left
        """
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
