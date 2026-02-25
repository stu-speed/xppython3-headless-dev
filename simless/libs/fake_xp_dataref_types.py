from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sshd_extensions.dataref_manager import DRefType


# XPLM data type bitmask constants
Type_Unknown = 0
Type_Int = 1
Type_Float = 2
Type_Double = 4
Type_FloatArray = 8
Type_IntArray = 16
Type_Data = 32


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

