# simless/libs/fake_xp_types.py

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any, Callable, Dict, List, MutableSequence, Optional, Sequence, Tuple

from simless.libs.fake_xp_constants import Type_Data, Type_FloatArray, Type_IntArray, lookup_constant_name
from xp_typing import (XPLMCommandPhase, XPLMCommandRef, XPLMCursorStatus, XPLMDataRef, XPLMDataTypeID, XPLMMenuCheck,
                       XPLMMenuID, XPLMMouseStatus, XPLMWindowDecoration, XPLMWindowID, XPLMWindowLayer, XPWidgetClass,
                       XPWidgetID, XPWidgetMessage, XPWidgetPropertyID)

XPWidgetCallback = Callable[[XPWidgetMessage | int, XPWidgetID, Any, Any], int]

ReadScalar = Callable[[Any], float | int]
WriteScalar = Callable[[Any, float | int], None]
ReadArray = Callable[
    [Any, Optional[MutableSequence[int | float]], int, int],
    int
]
WriteArray = Callable[
    [Any, Sequence[int | float], int, int],
    None
]



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
    Unified in‑memory representation of an X‑Plane DataRef.

    A FakeDataRef models the lifecycle and provider semantics of a real DataRef.
    It supports three phases, derived from attributes:

        D — Dummy
            Created with minimal information. Type and value are provisional
            until promotion.

        A — Accessor
            Backed by registerDataAccessor callbacks. Reads/writes are delegated
            to provider functions.

        X — Canonical
            Backed by authoritative metadata (e.g., bridge META). Type, size,
            and storage are fixed and fully known.
    """

    # -------------------------
    # Identity
    # -------------------------
    path: str
    df_id: XPLMDataRef

    # -------------------------
    # Type & shape (authoritative)
    # -------------------------
    type: XPLMDataTypeID | int  # xp.Type_Float, xp.Type_Int, xp.Type_FloatArray, etc.
    writable: bool
    size: int  # scalar=1, array=N

    # -------------------------
    # Storage
    # -------------------------
    value: Any  # scalar (float) or array (list/bytearray)

    # -------------------------
    # Accessor callbacks (A-phase)
    # -------------------------
    read_scalar: Optional[ReadScalar]
    write_scalar: Optional[WriteScalar]
    read_array: Optional[ReadArray]
    write_array: Optional[WriteArray]

    read_refcon: Any
    write_refcon: Any

    # -------------------------
    # Dummy flag
    # -------------------------
    dummy: bool

    last_modified: float = field(default_factory=time.monotonic)

    # ============================================================
    # Derived properties
    # ============================================================

    @property
    def is_array(self) -> bool:
        """
        True for array-typed refs (including 1-element arrays).

        Scalar vs array is determined by dtype, NOT by size.
        """
        return bool(self.type & (Type_FloatArray | Type_IntArray | Type_Data))

    @property
    def dynamic_array(self) -> bool:
        """
        True if the dataref's array length is not fixed.

        • DATA → always dynamic
        • Accessor-backed arrays → dynamic
        • Numeric arrays with size==0 → dynamic (rare)
        • Everything else → fixed
        """
        if Type_Data:
            return True

        if self.read_array is not None or self.write_array is not None:
            return True

        if (Type_FloatArray | Type_IntArray) and self.size == 0:
            return True

        return False

    @property
    def phase(self) -> str:
        """
        Derived lifecycle phase:
          D = Dummy      (dummy=True)
          A = Accessor   (dummy=False and callbacks present)
          X = Canonical  (dummy=False and no callbacks)
        """
        if self.dummy:
            return "D"
        if self.read_scalar or self.read_array:
            return "A"
        return "X"


# ---------------------------------------------------------------------------
# Strongly-typed coordinate spaces
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class XPPoint:
    """
    XP-global point in XPGraphics coordinate space.

    Coordinate system:
        • Origin: bottom-left of the X-Plane screen
        • X increases to the right
        • Y increases upward
    """

    x: int
    y: int


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
        """Return the width of the XP rectangle."""
        return self.right - self.left

    @property
    def height(self) -> int:
        """Return the height of the XP rectangle."""
        return self.top - self.bottom

    def __repr__(self):
        return (
            f"XPGeom("
            f"L={self.left}, T={self.top}, "
            f"R={self.right}, B={self.bottom}, "
            f"W={self.width}, H={self.height})"
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        """Return geometry as (left, top, right, bottom)."""
        return self.left, self.top, self.right, self.bottom

    # ------------------------------------------------------------
    # XP → DPG transform (XPGraphics → DPG client-space)
    # ------------------------------------------------------------
    def to_dpg(self, screen_h: int) -> "DPGGeom":
        """
        Convert XPGraphics coordinates to DearPyGui client-space.

        Args:
            screen_h: Height of the DPG client area in pixels.

        Returns:
            DPGGeom representing the same rectangle in DPG coordinates.
        """
        dpg_x = self.left
        dpg_y = screen_h - self.top  # top-aligned transform
        return DPGGeom(dpg_x, dpg_y, self.width, self.height)

    # ------------------------------------------------------------
    # DPG → XP transform (DPG client-space → XPGraphics)
    # ------------------------------------------------------------
    @classmethod
    def from_dpg(cls, dpg: DPGGeom, screen_h: int) -> XPGeom:
        """
        Convert DearPyGui client-space geometry to XPGraphics coordinates.

        Args:
            dpg:      DPGGeom rectangle.
            screen_h: Height of the DPG client area in pixels.

        Returns:
            XPGeom representing the same rectangle in XPGraphics coordinates.
        """
        left = dpg.x
        top = screen_h - dpg.y
        right = left + dpg.width
        bottom = top - dpg.height
        return cls(left, top, right, bottom)

    def contains(self, pt: XPPoint) -> bool:
        """
        Test whether an XP-global point lies inside this XP rectangle.
        """
        return (self.left <= pt.x <= self.right) and (self.bottom <= pt.y <= self.top)


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

    def __repr__(self):
        return (
            f"DPGGeom("
            f"({self.x},{self.y}), "
            f"W={self.width}, H={self.height})"
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        """Return geometry as (x, y, width, height)."""
        return self.x, self.y, self.width, self.height

    # ------------------------------------------------------------
    # DPG → XP transform (DPG client-space → XPGraphics)
    # ------------------------------------------------------------
    def to_xp(self, screen_h: int) -> XPGeom:
        """
        Convert DearPyGui client-space geometry to XPGraphics coordinates.

        Args:
            screen_h: Height of the DPG client area in pixels.

        Returns:
            XPGeom representing the same rectangle in XPGraphics coordinates.
        """
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
        """
        Convert XPGraphics geometry to DearPyGui client-space.

        Args:
            xp:       XPGeom rectangle.
            screen_h: Height of the DPG client area in pixels.

        Returns:
            DPGGeom representing the same rectangle in DPG coordinates.
        """
        return xp.to_dpg(screen_h)


@dataclass(slots=True)
class LocalGeom:
    """
    Widget-local geometry.

    Coordinate system:
        • Origin: top-left of the parent widget (or window client area)
        • Y increases downward
        • Stored as (x, y, width, height)

    XPGeom is derived on demand using client_xpgeom.
    """

    x: int
    y: int
    width: int
    height: int

    # ------------------------------------------------------------
    # Factory: XPGeom (absolute) → LocalGeom (parent-relative)
    # ------------------------------------------------------------
    @classmethod
    def from_xpgeom(cls, xpgeom: XPGeom, frame_geom: XPGeom) -> "LocalGeom":
        """
        Convert absolute XPGeom (screen-space, bottom-left origin)
        into LocalGeom (parent-relative, top-left origin).

        Args:
            xpgeom:      Absolute XPGeom of the widget.
            frame_geom: Absolute XPGeom of the parent client area.

        Returns:
            LocalGeom instance.
        """

        # XPGeom: bottom-left origin
        # LocalGeom: top-left origin

        local_x = xpgeom.left - frame_geom.left
        local_y = frame_geom.top - xpgeom.top

        return cls(
            x=local_x,
            y=local_y,
            width=xpgeom.width,
            height=xpgeom.height,
        )

    # ------------------------------------------------------------
    # LocalGeom → XPGeom (absolute)
    # ------------------------------------------------------------
    def to_xp_geom(self, frame_xpgeom: XPGeom) -> XPGeom:
        abs_left = frame_xpgeom.left + self.x
        abs_top = frame_xpgeom.top - self.y
        abs_right = abs_left + self.width
        abs_bottom = abs_top - self.height
        return XPGeom(abs_left, abs_top, abs_right, abs_bottom)

    # ------------------------------------------------------------
    # LocalGeom → DPGGeom (direct mapping)
    # ------------------------------------------------------------
    def to_local_dpg_geom(self) -> DPGGeom:
        return DPGGeom(self.x, self.y, self.width, self.height)


@dataclass(slots=True)
class WidgetInfo:
    """
    Pure XP-side state capsule for a single widget.

    Stores ONLY LocalGeom (top-left origin, parent-relative).
    XPGeom and DPGGeom are derived on demand.

    This mirrors the real XPWidget model:
        • Widgets do NOT store global screen coordinates.
        • All geometry is interpreted relative to the parent.
        • Root widgets interpret LocalGeom relative to the window client area.
    """

    wid: XPWidgetID
    widget_class: XPWidgetClass
    window: WindowExInfo
    local_geom: LocalGeom

    # Hierarchy
    parent: Optional[XPWidgetID] = None
    _children: list[XPWidgetID] = field(default_factory=list)

    # XP state
    _descriptor: str = ""
    _visible: bool = True

    # Non-root handles
    dpg_id: Optional[str] = None
    container_id: Optional[str] = None

    # Properties + callbacks
    _properties: Dict[XPWidgetPropertyID | int, Any] = field(default_factory=dict)
    _callbacks: List[XPWidgetCallback] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"<Widget {self.wid} "
            f"class={lookup_constant_name(self.widget_class, 'WidgetClass_')} "
            f"descriptor={self._descriptor}>"
        )

    # ------------------------------------------------------------
    # GEOMETRY ACCESSORS
    # ------------------------------------------------------------
    @property
    def xp_geom(self) -> XPGeom:
        """Absolute XPGraphics geometry derived from LocalGeom."""
        return self.local_geom.to_xp_geom(self.window.frame)

    @property
    def local_dpg_geom(self) -> DPGGeom:
        """DPG-local geometry derived from LocalGeom."""
        return self.local_geom.to_local_dpg_geom()

    # ------------------------------------------------------------
    # GEOMETRY MUTATION
    # ------------------------------------------------------------
    def set_abs_xpgeom(self, abs_geom: XPGeom) -> None:
        """
        Accepts ABSOLUTE XPGeom and converts it to LocalGeom.
        Used for later geometry changes.
        """

        self.local_geom = LocalGeom.from_xpgeom(abs_geom, self.window.frame)
        self.window._dirty_widgets = True

    # ------------------------------------------------------------
    # VISIBILITY / DESCRIPTOR / PROPERTIES
    # ------------------------------------------------------------
    @property
    def visible(self) -> bool:
        return self._visible

    def set_visible(self, value: bool) -> None:
        self._visible = value
        self.window._dirty_widgets = True

    @property
    def descriptor(self) -> str:
        return self._descriptor

    def set_descriptor(self, value: str) -> None:
        self._descriptor = value
        self.window._dirty_widgets = True

    @property
    def properties(self) -> Dict[XPWidgetPropertyID | int, Any]:
        return self._properties

    def set_property(self, prop: XPWidgetPropertyID | int, value: Any) -> None:
        self._properties[prop] = value
        self.window._dirty_widgets = True

    @property
    def callbacks(self) -> list[XPWidgetCallback]:
        return self._callbacks

    def add_callback(self, cb: XPWidgetCallback) -> None:
        self._callbacks.append(cb)

    def remove_callback(self, cb: XPWidgetCallback) -> None:
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    # ------------------------------------------------------------
    # HIERARCHY
    # ------------------------------------------------------------
    @property
    def children(self) -> List[XPWidgetID]:
        return self._children

    def add_child(self, child_id: XPWidgetID) -> None:
        self._children.append(child_id)
        self.window._dirty_widgets = True

    def remove_child(self, child_id: XPWidgetID) -> None:
        if child_id in self._children:
            self._children.remove(child_id)
            self.window._dirty_widgets = True


@dataclass(slots=True)
class WindowExInfo:
    """Authoritative XP-side model of a WindowEx window."""

    # XP identity
    wid: XPLMWindowID

    # XP authoritative geometry
    _frame: XPGeom
    _client: XPGeom

    # XP state
    _visible: bool
    _decoration: XPLMWindowDecoration
    _layer: XPLMWindowLayer

    # XP callback hooks
    draw_cb: Optional[Callable[[XPLMWindowID, Any], None]]
    click_cb: Optional[
        Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
    ]
    right_click_cb: Optional[
        Callable[[XPLMWindowID, int, int, XPLMMouseStatus, Any], int]
    ]
    key_cb: Optional[Callable[[XPLMWindowID, int, int, int, Any, int], int]]
    cursor_cb: Optional[Callable[[XPLMWindowID, int, int, Any], XPLMCursorStatus]]
    wheel_cb: Optional[Callable[[XPLMWindowID, int, int, int, int, Any], int]]
    refcon: Any

    # Backend (DPG) — created lazily
    _dpg_window_id: Optional[str] = None
    _drawlist_id: Optional[str] = None

    # Dirty flags
    _dirty_xp_to_dpg: bool = True  # XP window state changed
    _dirty_dpg_to_xp: bool = False  # DPG window state changed
    _dirty_widgets: bool = False  # Widget tree changed (requires _render_widgets)

    # Widget tree
    _widget_root: Optional[XPWidgetID] = None
    _z_order: list[XPWidgetID] = field(default_factory=list)
    _focused_widget: Optional[XPWidgetID] = None
    _close_widget: Optional[XPWidgetID] = None

    # Optional back-reference to a window manager providing decoration metrics
    window_manager: Any = None

    # ------------------------------------------------------------
    # PUBLIC READ-ONLY GEOMETRY
    # ------------------------------------------------------------

    @property
    def frame(self) -> XPGeom:
        """Return the authoritative XP-global frame rectangle."""
        return self._frame

    @property
    def client(self) -> XPGeom:
        """Return the authoritative XP-global client rectangle."""
        return self._client

    @property
    def dpg_tag(self) -> Optional[str]:
        """Return the DearPyGui window tag, if created."""
        return self._dpg_window_id

    @property
    def drawlist_tag(self) -> Optional[str]:
        """Return the DearPyGui drawlist tag, if created."""
        return self._drawlist_id

    # ------------------------------------------------------------
    # XP-originated geometry setters (XP → DPG)
    # ------------------------------------------------------------

    def set_frame_from_xp(self, geom: XPGeom) -> None:
        """Set the frame rectangle from XPGraphics coordinates."""
        self._frame = geom
        self._dirty_xp_to_dpg = True

    def set_client_from_xp(self, geom: XPGeom) -> None:
        """Set the client rectangle from XPGraphics coordinates."""
        self._client = geom
        self._dirty_xp_to_dpg = True

    # ------------------------------------------------------------
    # DPG-originated geometry setters (DPG → XP)
    # ------------------------------------------------------------

    def set_frame_from_dpg(self, geom: DPGGeom, client_h: int) -> None:
        """Set the frame rectangle from DearPyGui client-space geometry."""
        self._frame = geom.to_xp(client_h)
        self._dirty_dpg_to_xp = True

    def set_client_from_dpg(self, geom: DPGGeom, client_h: int) -> None:
        """Set the client rectangle from DearPyGui client-space geometry."""
        self._client = geom.to_xp(client_h)
        self._dirty_dpg_to_xp = True

    # ------------------------------------------------------------
    # XP STATE SETTERS
    # ------------------------------------------------------------

    @property
    def visible(self) -> bool:
        """Return True if the window is visible."""
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        """Set window visibility and mark geometry as dirty."""
        self._visible = value
        self._dirty_xp_to_dpg = True

    @property
    def decoration(self) -> XPLMWindowDecoration:
        """Return the current window decoration."""
        return self._decoration

    @decoration.setter
    def decoration(self, value: XPLMWindowDecoration) -> None:
        """Set window decoration and mark geometry as dirty."""
        self._decoration = value
        self._dirty_xp_to_dpg = True

    @property
    def layer(self) -> XPLMWindowLayer:
        """Return the current window layer."""
        return self._layer

    @layer.setter
    def layer(self, value: XPLMWindowLayer) -> None:
        """Set window layer and mark geometry as dirty."""
        self._layer = value
        self._dirty_xp_to_dpg = True

    # ------------------------------------------------------------
    # WIDGET TREE
    # ------------------------------------------------------------

    @property
    def widget_root(self) -> Optional[XPWidgetID]:
        """Return the root widget ID for this window, if any."""
        return self._widget_root

    def set_widget_root(self, wid: Optional[XPWidgetID]) -> None:
        """Set the root widget ID and mark widgets as dirty."""
        self._widget_root = wid
        self._dirty_widgets = True

    @property
    def widget_z_order(self) -> list[XPWidgetID]:
        """Return the z-order list of widgets for this window."""
        return self._z_order

    def add_to_widget_z_order(self, wid: XPWidgetID) -> None:
        """Append a widget to the z-order and mark widgets as dirty."""
        self._z_order.append(wid)
        self._dirty_widgets = True

    def remove_from_widget_z_order(self, wid: XPWidgetID) -> None:
        """Remove a widget from the z-order and clear focus if needed."""
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._dirty_widgets = True

        if self._focused_widget == wid:
            self._focused_widget = None

    def raise_widget(self, wid: XPWidgetID) -> None:
        """Bring a widget to the front of the z-order."""
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.append(wid)
            self._dirty_widgets = True

    def lower_widget(self, wid: XPWidgetID) -> None:
        """Send a widget to the back of the z-order."""
        if wid in self._z_order:
            self._z_order.remove(wid)
            self._z_order.insert(0, wid)
            self._dirty_widgets = True

    # ------------------------------------------------------------
    # WIDGET FOCUS HELPERS
    # ------------------------------------------------------------

    @property
    def focused_widget(self) -> Optional[XPWidgetID]:
        """Return the currently focused widget ID, if any."""
        return self._focused_widget

    def set_focused_widget(self, wid: Optional[XPWidgetID]) -> None:
        """Set the focused widget ID and mark widgets as dirty."""
        self._focused_widget = wid
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
    # ------------------------------------------------------------------
    xp_pt: Optional[XPPoint] = None

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
            xp_pt: Optional[XPPoint] = None,
            **kwargs: Any,
    ) -> "EventInfo":
        """Create an EventInfo with explicit XP coordinates."""
        return cls(kind=kind, xp_pt=xp_pt, **kwargs)

    @classmethod
    def from_dpg(
            cls,
            *,
            kind: EventKind,
            dpg_x: int,
            dpg_y: int,
            dpg_vp_height: int,
            **kwargs: Any,
    ) -> "EventInfo":
        """Create an EventInfo from DearPyGui coordinates.

        Converts DPG (top-left origin) to XP (bottom-left origin).
        """
        return cls(
            kind=kind,
            xp_pt=XPPoint(int(dpg_x), int(dpg_vp_height - dpg_y)),
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
    ADD_CHECKBOX = auto()

    # --------------------------------------------------
    # Item mutation
    # --------------------------------------------------
    CONFIGURE_ITEM = auto()
    SET_VALUE = auto()
    SHOW_ITEM = auto()
    HIDE_ITEM = auto()
    DELETE_ITEM = auto()
    BIND_ITEM_FONT = auto()

    # --------------------------------------------------
    # Menus (XPLMMenus → DearPyGui)
    # --------------------------------------------------
    ADD_MENU = auto()  # dpg.add_menu()
    ADD_MENU_ITEM = auto()  # dpg.add_menu_item()


@dataclass(frozen=True, slots=True)
class DPGCommand:
    """Deferred DearPyGui operation.

    Recorded during XP callbacks.
    Executed during frame replay only.
    """

    op: DPGOp

    # Routing
    target_drawlist: Optional[int | str] = None  # None for non-draw ops

    # Positional + keyword arguments for the DPG call
    args: Tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MenuRecord:
    menu_id: XPLMMenuID
    name: str
    dpg_tag: str
    parent_dpg_tag: str
    refcon: Any
    handler: Optional[Callable[[Any, Any], None]]
    items: List[MenuItemRecord] = field(default_factory=list)


@dataclass
class MenuItemRecord:
    name: str
    dpg_tag: str
    refcon: Any
    checked: XPLMMenuCheck
    enabled: bool
    separator: bool
    command: Optional[XPLMCommandRef]
    submenu_id: Optional[XPLMMenuID]


CommandCallback = Callable[[XPLMCommandRef, XPLMCommandPhase, Any], int]


@dataclass(slots=True)
class CommandHandlerRecord:
    callback: CommandCallback
    refcon: Any
    before: bool
    after: bool
