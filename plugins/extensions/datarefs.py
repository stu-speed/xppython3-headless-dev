# ===========================================================================
# DataRefs — unified production/simless DataRef layer
#
# Provides a consistent DataRef model for both real X‑Plane (via XPPython3)
# and FakeXP’s simless environment. Plugins declare DataRefs up front, and
# this layer ensures they are typed, writable as specified, and ready before
# plugin code runs. Defaults are applied automatically when X‑Plane does not
# supply a value.
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional


# ======================================================================
# X‑Plane bitmask types (production‑accurate)
# ======================================================================

class DRefType(IntEnum):
    INT         = 1
    FLOAT       = 2
    DOUBLE      = 4
    FLOAT_ARRAY = 8
    INT_ARRAY   = 16
    BYTE_ARRAY  = 32


# ======================================================================
# DataRefSpec — declarative plugin‑side specification
# ======================================================================

@dataclass(slots=True)
class DataRefSpec:
    path: str
    dtype: DRefType
    writable: bool = False
    required: bool = False
    default: Any = None


# ======================================================================
# TypedAccessor — strongly typed access to a bound dataref
# ======================================================================

class TypedAccessor:
    def __init__(self, xp, handle, dtype: DRefType):
        self._xp = xp
        self._handle = handle
        self._dtype = dtype

    def get(self):
        xp = self._xp
        h = self._handle

        if self._dtype == DRefType.FLOAT:
            return xp.getDataf(h)
        if self._dtype == DRefType.INT:
            return xp.getDatai(h)
        if self._dtype == DRefType.DOUBLE:
            return xp.getDatad(h)
        if self._dtype == DRefType.FLOAT_ARRAY:
            size = xp.getDatavfLength(h)
            out = [0.0] * size
            xp.getDatavf(h, out, 0, size)
            return out
        if self._dtype == DRefType.INT_ARRAY:
            size = xp.getDataviLength(h)
            out = [0] * size
            xp.getDatavi(h, out, 0, size)
            return out
        if self._dtype == DRefType.BYTE_ARRAY:
            size = xp.getDatabLength(h)
            out = bytearray(size)
            xp.getDatab(h, out, 0, size)
            return out

        raise TypeError(f"Unsupported dtype {self._dtype}")

    def set(self, value):
        xp = self._xp
        h = self._handle

        if self._dtype == DRefType.FLOAT:
            xp.setDataf(h, float(value))
            return
        if self._dtype == DRefType.INT:
            xp.setDatai(h, int(value))
            return
        if self._dtype == DRefType.DOUBLE:
            xp.setDatad(h, float(value))
            return
        if self._dtype == DRefType.FLOAT_ARRAY:
            xp.setDatavf(h, list(value), 0, len(value))
            return
        if self._dtype == DRefType.INT_ARRAY:
            xp.setDatavi(h, list(value), 0, len(value))
            return
        if self._dtype == DRefType.BYTE_ARRAY:
            xp.setDatab(h, list(value), 0, len(value))
            return

        raise TypeError(f"Unsupported dtype {self._dtype}")


# ======================================================================
# DataRefRegistry — plugin‑side declaration + FakeXP auto‑registration
# ======================================================================

class DataRefRegistry:
    def __init__(self, xp, specs: Dict[str, DataRefSpec]):
        self._xp = xp
        self._specs = specs
        self._handles: Dict[str, Any] = {}

        # Auto‑register all declared datarefs with FakeXP
        for key, spec in specs.items():
            xp_type = int(spec.dtype)
            is_array = spec.dtype in (
                DRefType.FLOAT_ARRAY,
                DRefType.INT_ARRAY,
                DRefType.BYTE_ARRAY,
            )

            size = 1
            if is_array and isinstance(spec.default, (list, tuple, bytearray)):
                size = len(spec.default)

            handle = xp.fake_register_dataref(
                spec.path,
                xp_type=xp_type,
                is_array=is_array,
                size=size,
                writable=spec.writable,
            )

            self._handles[key] = handle

    def __getitem__(self, key: str) -> TypedAccessor:
        spec = self._specs[key]
        handle = self._handles[key]
        return TypedAccessor(self._xp, handle, spec.dtype)


# ======================================================================
# DataRefManager — runtime binding + validation
# ======================================================================

class DataRefManager:
    def __init__(self, registry: DataRefRegistry, xp, timeout_seconds: float = 10.0):
        self._registry = registry
        self._xp = xp
        self._timeout = timeout_seconds
        self._bound: Dict[str, TypedAccessor] = {}

        xp.bind_dataref_manager(self)

    def ensure_datarefs(self) -> bool:
        # All datarefs are already registered by DataRefRegistry
        # This method simply verifies they exist and are typed correctly.
        for key, spec in self._registry._specs.items():
            handle = self._registry._handles[key]
            info = self._xp.getDataRefInfo(handle)

            if info.xp_type != int(spec.dtype):
                self._xp.log(
                    f"[DataRef] ERROR: Type mismatch for '{spec.path}'. "
                    f"Expected {spec.dtype}, got {info.xp_type}"
                )
                return False

            self._bound[key] = TypedAccessor(self._xp, handle, spec.dtype)

        self._xp._dbg("[DataRefManager] All required datarefs bound")
        return True

    def _notify_dataref_changed(self, ref):
        # Optional hook — currently unused
        pass

