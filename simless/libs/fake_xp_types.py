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
class WGeom:
    """
    XPWidget geometry in window-local coordinates.

    Coordinate system:
        • Origin: (0, 0) at the top-left of the window's client area
        • X increases to the right
        • Y increases downward
        • Geometry is stored as (left, top, right, bottom)

    Width  = right  - left
    Height = bottom - top
    """

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    def contains(self, x: int, y: int) -> bool:
        return (self.left <= x <= self.right) and (self.top <= y <= self.bottom)


@dataclass(slots=True)
class WidgetInfo:
    """
    Authoritative record for a single XPWidget.
    """

    # Identity
    wid: XPWidgetID
    widget_class: XPWidgetClass
    window: "WindowExInfo"

    # Authoritative XP geometry
    _geometry: WGeom

    # Hierarchy
    parent: Optional[XPWidgetID] = None
    _children: list[XPWidgetID] = field(default_factory=list)

    # XPWidget state
    _descriptor: str = ""
    _last_descriptor: str = "<<NONE>>"   # updated only by DPG sync
    _visible: bool = True

    # Backend handles
    dpg_id: Optional[str] = None
    container_id: Optional[str] = None

    # DPG geometry state
    geom_applied: bool = False
    container_geom_applied: Optional[DPGGeom] = None

    # XPWidget properties and callbacks
    _properties: Dict[XPWidgetPropertyID|int, Any] = field(default_factory=dict)
    _callbacks: List[XPWidgetCallback] = field(default_factory=list)

    # Interaction state
    edit_buffer: Optional[str] = None

    # ------------------------------------------------------------
    # PROTECTED SETTERS (all mutations dirty the owning WindowEx)
    # ------------------------------------------------------------

    @property
    def geometry(self) -> WGeom:
        return self._geometry

    @geometry.setter
    def geometry(self, value: WGeom):
        self._geometry = value
        self.geom_applied = False
        self.container_geom_applied = None
        self.window._dirty_widgets = True

    @property
    def descriptor(self) -> str:
        return self._descriptor

    def set_descriptor(self, value: str):
        self._descriptor = value
        self.window._dirty_widgets = True

    @property
    def visible(self) -> bool:
        return self._visible

    def set_visible(self, value: bool):
        self._visible = value
        self.window._dirty_widgets = True

    @property
    def properties(self) -> Dict[XPWidgetPropertyID|int, Any]:
        return self._properties

    def set_property(self, prop: XPWidgetPropertyID, value: Any):
        self._properties[prop] = value
        self.window._dirty_widgets = True

    @property
    def callbacks(self) -> List[XPWidgetCallback]:
        return self._callbacks

    def add_callback(self, cb: XPWidgetCallback):
        self._callbacks.append(cb)

    def remove_callback(self, cb: XPWidgetCallback):
        self._callbacks.remove(cb)

    @property
    def children(self) -> List[XPWidgetID]:
        return self._children

    def add_child(self, child_id: XPWidgetID):
        self._children.append(child_id)
        self.window._dirty_widgets = True

    def remove_child(self, child_id: XPWidgetID):
        if child_id in self._children:
            self._children.remove(child_id)
            self.window._dirty_widgets = True

    # ------------------------------------------------------------
    # DERIVED GEOMETRY HELPERS (read‑only)
    # ------------------------------------------------------------

    @property
    def left(self) -> int:
        return self._geometry.left

    @property
    def top(self) -> int:
        return self._geometry.top

    @property
    def right(self) -> int:
        return self._geometry.right

    @property
    def bottom(self) -> int:
        return self._geometry.bottom

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(slots=True)
class XPGeom:
    """
    XP window geometry using the XPGraphics coordinate system.

    Coordinate system:
        • Origin: bottom-left of the X-Plane screen
        • Y increases upward
        • Rect is defined as (left, top, right, bottom) with top > bottom

    Transform rules:
        XP → DPG:
            DearPyGui client coordinates use a top-left origin with Y increasing downward.
            To convert XPGraphics → DPG client space:
                dpg_x = xp_left
                dpg_y = screen_h - xp_top

        DPG → XP:
            Reverse the transform:
                xp_top    = screen_h - dpg_y
                xp_bottom = xp_top - dpg_height

    This class provides a clean, symmetric round-trip between XPGraphics
    and DPG client-space coordinates.
    """

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.top - self.bottom

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    # ------------------------------------------------------------
    # XP → DPG transform (XPGraphics → DPG client-space)
    # ------------------------------------------------------------
    def to_dpg(self, screen_h: int) -> "DPGGeom":
        dpg_x = self.left
        dpg_y = screen_h - self.top   # top-aligned transform
        return DPGGeom(dpg_x, dpg_y, self.width, self.height)

    # ------------------------------------------------------------
    # DPG → XP transform (DPG client-space → XPGraphics)
    # ------------------------------------------------------------
    @classmethod
    def from_dpg(cls, dpg: "DPGGeom", screen_h: int) -> "XPGeom":
        left = dpg.x
        top = screen_h - dpg.y
        right = left + dpg.width
        bottom = top - dpg.height
        return cls(left, top, right, bottom)

    def contains(self, xp_x: int, xp_y: int) -> bool:
        return (self.left <= xp_x <= self.right) and (self.bottom <= xp_y <= self.top)


@dataclass(slots=True)
class DPGGeom:
    """
    DearPyGui window geometry in client-space coordinates.

    Coordinate system:
        • Origin: top-left of the DPG client area
        • Y increases downward
        • Rect is defined as (x, y, width, height)
          where (x, y) is the top-left corner.

    Transform rules:
        DPG → XP (XPGraphics):
            XPGraphics uses a bottom-left origin with Y increasing upward.
            To convert DPG client-space → XPGraphics:
                xp_left   = dpg_x
                xp_top    = screen_h - dpg_y
                xp_right  = xp_left + width
                xp_bottom = xp_top  - height

        XP → DPG:
            Reverse the transform:
                dpg_x = xp_left
                dpg_y = screen_h - xp_top

    This class provides the inverse mapping of XPGeom.to_dpg(),
    ensuring a clean, symmetric round-trip between XPGraphics and
    DPG client-space coordinates.
    """

    x: int
    y: int
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    # ------------------------------------------------------------
    # DPG → XP transform (DPG client-space → XPGraphics)
    # ------------------------------------------------------------
    def to_xp(self, screen_h: int) -> XPGeom:
        left = self.x
        top = screen_h - self.y
        right = left + self.width
        bottom = top - self.height
        return XPGeom(left, top, right, bottom)

    # ------------------------------------------------------------
    # XP → DPG transform (XPGraphics → DPG client-space)
    # ------------------------------------------------------------
    @classmethod
    def from_xp(cls, xp: XPGeom, screen_h: int) -> "DPGGeom":
        return xp.to_dpg(screen_h)


@dataclass(slots=True)
class WindowExInfo:
    """Authoritative XP-side model of a WindowEx window."""

    # XP identity
    wid: XPLMWindowID | int

    # XP authoritative geometry
    _frame: XPGeom
    _client: XPGeom

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

    # Backend (DPG) — created lazily
    _dpg_window_id: Optional[str] = None
    _drawlist_id: Optional[str] = None

    # Dirty flags
    _dirty_xp_to_dpg: bool = True      # XP window state changed
    _dirty_dpg_to_xp: bool = False     # DPG window state changed
    _dirty_widgets: bool = True        # Widget tree changed (requires _render_widgets)

    # Widget tree root
    _widget_root: Optional[XPWidgetID] = None

    # XP WIDGET STATE (PER-WINDOW)
    _z_order: list[XPWidgetID] = field(default_factory=list)
    _focused_widget: Optional[XPWidgetID] = None

    # ------------------------------------------------------------
    # PUBLIC READ-ONLY GEOMETRY
    # ------------------------------------------------------------

    @property
    def frame(self) -> XPGeom:
        return self._frame

    @property
    def client(self) -> XPGeom:
        return self._client

    @property
    def dpg_tag(self) -> Optional[str]:
        return self._dpg_window_id

    @property
    def drawlist_tag(self) -> Optional[str]:
        return self._drawlist_id

    # ------------------------------------------------------------
    # XP-originated geometry setters (XP → DPG)
    # ------------------------------------------------------------

    def set_frame_from_xp(self, geom: XPGeom) -> None:
        self._frame = geom
        self._dirty_xp_to_dpg = True

    def set_client_from_xp(self, geom: XPGeom) -> None:
        self._client = geom
        self._dirty_xp_to_dpg = True

    # ------------------------------------------------------------
    # DPG-originated geometry setters (DPG → XP)
    # ------------------------------------------------------------

    def set_frame_from_dpg(self, geom: DPGGeom, client_h: int) -> None:
        self._frame = geom.to_xp(client_h)
        self._dirty_dpg_to_xp = True

    def set_client_from_dpg(self, geom: DPGGeom, client_h: int) -> None:
        self._client = geom.to_xp(client_h)
        self._dirty_dpg_to_xp = True

    # ------------------------------------------------------------
    # XP STATE SETTERS
    # ------------------------------------------------------------

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool):
        self._visible = value
        self._dirty_xp_to_dpg = True

    @property
    def decoration(self) -> XPLMWindowDecoration:
        return self._decoration

    @decoration.setter
    def decoration(self, value: XPLMWindowDecoration):
        self._decoration = value
        self._dirty_xp_to_dpg = True

    @property
    def layer(self) -> XPLMWindowLayer | int:
        return self._layer

    @layer.setter
    def layer(self, value: XPLMWindowLayer | int):
        self._layer = value
        self._dirty_xp_to_dpg = True

    # ------------------------------------------------------------
    # WIDGET TREE
    # ------------------------------------------------------------

    @property
    def widget_root(self) -> Optional[XPWidgetID]:
        return self._widget_root

    def set_widget_root(self, wid: Optional[XPWidgetID]) -> None:
        self._widget_root = wid
        self._dirty_widgets = True

    # ------------------------------------------------------------
    # WIDGET Z-ORDER HELPERS
    # ------------------------------------------------------------

    @property
    def z_order(self) -> list[XPWidgetID]:
        return self._z_order

    def add_to_z_order(self, wid: XPWidgetID) -> None:
        self._z_order.append(wid)
        self._dirty_widgets = True

    def remove_from_z_order(self, wid: XPWidgetID) -> None:
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._dirty_widgets = True

        if self._focused_widget == wid:
            self._focused_widget = None

    def raise_widget(self, wid: XPWidgetID) -> None:
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.append(wid)
            self._dirty_widgets = True

    def lower_widget(self, wid: XPWidgetID) -> None:
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)
            self._dirty_widgets = True

    # ------------------------------------------------------------
    # WIDGET FOCUS HELPERS
    # ------------------------------------------------------------

    @property
    def focused_widget(self) -> Optional[XPWidgetID]:
        return self._focused_widget

    def set_focused_widget(self, wid: Optional[XPWidgetID]) -> None:
        self._focused_widget = wid
        self._dirty_widgets = True

    def clear_widget_focus(self) -> None:
        self._focused_widget = None
        self._dirty_widgets = True


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
