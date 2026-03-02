from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from sshd_extensions.dataref_manager import DRefType
from XPPython3.xp_typing import XPWidgetClass, XPWidgetID, XPWidgetPropertyID

# XPLM data type bitmask constants
Type_Unknown = 0
Type_Int = 1
Type_Float = 2
Type_Double = 4
Type_FloatArray = 8
Type_IntArray = 16
Type_Data = 32

XPWidgetCallback = Callable[[int, int, Any, Any], int]


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


@dataclass
class WidgetInfo:
    """Authoritative record for a single XPWidget.

    This dataclass represents the complete, XP‑semantic and XP-geometry state of a widget.
    It is the single source of truth for widget identity, hierarchy, geometry,
    visibility, properties, and callbacks.

    DearPyGui‑specific fields are included only as opaque handles for a
    rendering backend. They are never interpreted or mutated by the XP
    widget API layer.

    Attributes:
        wid: Unique XPWidget identifier.
        widget_class: XPWidgetClass enum value describing the widget type.
        parent: Parent widget ID, or XPWidgetID(0) if this widget is a root.
        descriptor: Human‑readable descriptor string (label, caption, etc.).
        geometry: Global XP screen‑space geometry as (x, top, width, height).
        visible: Whether the widget is currently visible.
        properties: Mapping of XPWidgetPropertyID to property values.
        callbacks: List of registered XPWidget callbacks.

        dpg_id: Internal DearPyGui item ID for this widget, if any.
        container_id: DearPyGui child_window container ID for controls;
            for XP windows, this is equal to dpg_id.

        geom_applied: Whether the current geometry has been applied by the
            rendering backend.
        container_geom_applied: Last applied container geometry as
            (local_x, local_y, width, height), or None if not applied.

        edit_buffer: Temporary text buffer for editable widgets such as
            text fields.
    """

    # XP authoritative state
    wid: XPWidgetID
    widget_class: XPWidgetClass
    parent: XPWidgetID
    descriptor: str
    geometry: Tuple[int, int, int, int]
    visible: bool = True
    properties: Dict[XPWidgetPropertyID, Any] = field(default_factory=dict)
    callbacks: List[XPWidgetCallback] = field(default_factory=list)

    # DearPyGui representation (internal only)
    dpg_id: Optional[int] = None
    container_id: Optional[int] = None

    # Geometry lifecycle
    geom_applied: bool = False
    container_geom_applied: Optional[Tuple[int, int, int, int]] = None

    # Interaction state
    edit_buffer: Optional[str] = None
