# ===========================================================================
# DataRefs — unified production/simless DataRef layer
#
# Provides a consistent DataRef model for both real X‑Plane (via XPPython3)
# and FakeXP’s simless environment. Plugins declare DataRefs up front, and
# this layer ensures they are typed, writable as specified, and ready before
# plugin code runs. Defaults are applied automatically when X‑Plane does not
# supply a value.
#
# Responsibilities:
#   • Register DataRefs from declarative specs (path, type, writable, default, required)
#   • Guarantee readiness: required DataRefs must resolve; optional ones fall back to defaults
#   • Provide the common X‑Plane get/set API surface:
#         getDatai / setDatai
#         getDataf / setDataf
#         getDatad / setDatad
#         getDatavi / setDatavi
#         getDatavf / setDatavf
#         getDatab / setDatab
#   • Maintain correct scalar/array behavior and enforce type‑correct access
#   • Notify DataRefManager when values change
#
# Production notes:
#   • Resolves real XPLMDataRef handles and uses XPLMGet*/Set* APIs
#   • Defaults apply only when X‑Plane does not provide a value
#
# Simless notes:
#   • Uses FakeRefInfo handles with deterministic in‑memory storage
#   • Dummy refs are promoted on first access with inferred type + defaults
#
# Design goals:
#   • One DataRef definition and behavior model for both environments
#   • Predictable initialization, strict typing, and clear defaults
# ===========================================================================

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Protocol, Tuple

from XPPython3.xp_typing import XPLMDataRefInfo_t
from .xp_interface import (
    XPInterface,
    DataRefHandle,
    DataRefInfo,
)


class DRefType(Enum):
    INT = "int"
    FLOAT = "float"
    DOUBLE = "double"
    INT_ARRAY = "int_array"
    FLOAT_ARRAY = "float_array"
    BYTE_ARRAY = "byte_array"


@dataclass(slots=True)
class DataRefSpec:
    path: str
    dtype: DRefType | None = None
    writable: bool | None = None
    description: str | None = None
    required: bool = True
    default: Any | None = None


class FakeRefInfoProto(Protocol):
    path: str
    xp_type: int | None
    writable: bool
    is_array: bool
    size: int
    dummy: bool


def _map_xplane_type(xp_type: int) -> DRefType:
    if xp_type & 1:
        return DRefType.INT
    if xp_type & 2:
        return DRefType.FLOAT
    if xp_type & 4:
        return DRefType.DOUBLE
    if xp_type & 8:
        return DRefType.FLOAT_ARRAY
    if xp_type & 16:
        return DRefType.INT_ARRAY
    if xp_type & 32:
        return DRefType.BYTE_ARRAY
    raise ValueError(f"Unknown X‑Plane dataref type flag: {xp_type}")


def _infer_default_dtype(default: Any) -> DRefType | None:
    if default is None:
        return None
    if isinstance(default, int):
        return DRefType.INT
    if isinstance(default, float):
        return DRefType.FLOAT
    if isinstance(default, list):
        if all(isinstance(x, int) for x in default):
            return DRefType.INT_ARRAY
        if all(isinstance(x, float) for x in default):
            return DRefType.FLOAT_ARRAY
    if isinstance(default, (bytes, bytearray)):
        return DRefType.BYTE_ARRAY
    return None


def _normalize_info_for_binding(
    xp: XPInterface,
    path: str,
    info: DataRefInfo,
) -> Tuple[int, bool, bool, int] | None:
    if hasattr(info, "xp_type") and hasattr(info, "dummy"):
        xp_type = getattr(info, "xp_type", None)
        dummy = bool(getattr(info, "dummy", False))
        if dummy or xp_type is None:
            xp.log(f"[DataRef] Not bound yet: {path}")
            return None

        writable = bool(getattr(info, "writable", False))
        is_array = bool(getattr(info, "is_array", False))
        size = int(getattr(info, "size", 0))
        return int(xp_type), writable, is_array, size

    if isinstance(info, XPLMDataRefInfo_t):
        xp_type = int(info.type)
        writable = bool(info.writable)
        is_array = bool(xp_type & (8 | 16 | 32))
        size = 0
        return xp_type, writable, is_array, size

    raise TypeError(f"Unknown info type from getDataRefInfo: {type(info)}")


class TypedAccessor:
    _handle: DataRefHandle | None

    def __init__(self, xp: XPInterface, spec: DataRefSpec) -> None:
        self._xp = xp
        self._spec = spec
        self._handle = None

    @property
    def spec(self) -> DataRefSpec:
        return self._spec

    def try_bind(self) -> bool:
        if self._handle is not None:
            return True

        handle = self._xp.findDataRef(self._spec.path)
        self._handle = handle

        if handle is None:
            self._xp.log(f"[DataRef] Not found yet: {self._spec.path}")
            return False

        info = self._xp.getDataRefInfo(handle)
        normalized = _normalize_info_for_binding(self._xp, self._spec.path, info)
        if normalized is None:
            return False

        xp_type, writable, is_array, _ = normalized
        actual_dtype = _map_xplane_type(xp_type)

        expected = self._spec.dtype or _infer_default_dtype(self._spec.default)
        if expected is not None and actual_dtype != expected:
            self._xp.log(
                f"[DataRef] ERROR: Type mismatch for '{self._spec.path}'. "
                f"Expected {expected.value}, got {actual_dtype.value}. Binding aborted."
            )
            return False

        if self._spec.dtype is None:
            self._spec.dtype = actual_dtype
        if self._spec.writable is None:
            self._spec.writable = bool(writable)

        self._xp.log(f"[DataRef] Bound: {self._spec.path}")
        return True

    def get(self) -> Any:
        if self._handle is None:
            return self._spec.default

        dtype = self._spec.dtype
        if dtype is None:
            raise TypeError(f"DataRef '{self._spec.path}' has no dtype")

        match dtype:
            case DRefType.INT:
                return self._xp.getDatai(self._handle)
            case DRefType.FLOAT:
                return self._xp.getDataf(self._handle)
            case DRefType.DOUBLE:
                return self._xp.getDatad(self._handle)
            case DRefType.INT_ARRAY:
                return self._xp.getDatavi(self._handle)
            case DRefType.FLOAT_ARRAY:
                return self._xp.getDatavf(self._handle)
            case DRefType.BYTE_ARRAY:
                return self._xp.getDatab(self._handle)

        raise TypeError(f"Unsupported dtype: {dtype}")

    def set(self, value: Any) -> None:
        if not self._spec.writable:
            raise PermissionError(f"DataRef '{self._spec.path}' is read‑only")

        dtype = self._spec.dtype
        if dtype is None:
            raise TypeError(f"DataRef '{self._spec.path}' has no dtype")

        if self._handle is None:
            self._spec.default = value
            return

        match dtype:
            case DRefType.INT:
                self._xp.setDatai(self._handle, int(value))
            case DRefType.FLOAT:
                self._xp.setDataf(self._handle, float(value))
            case DRefType.DOUBLE:
                self._xp.setDatad(self._handle, float(value))
            case DRefType.INT_ARRAY:
                self._xp.setDatavi(self._handle, value)
            case DRefType.FLOAT_ARRAY:
                self._xp.setDatavf(self._handle, value)
            case DRefType.BYTE_ARRAY:
                self._xp.setDatab(self._handle, value)


class DataRefRegistry:
    def __init__(self, xp: XPInterface, specs: Mapping[str, DataRefSpec]) -> None:
        self._xp = xp
        self._accessors: Dict[str, TypedAccessor] = {
            name: TypedAccessor(xp, spec) for name, spec in specs.items()
        }

        for _, spec in specs.items():
            if hasattr(xp, "fake_register_dataref"):
                xp.fake_register_dataref(spec.path, spec.default, spec.writable)

    def __getitem__(self, name: str) -> TypedAccessor:
        return self._accessors[name]

    def items(self) -> Iterable[tuple[str, TypedAccessor]]:
        return self._accessors.items()


class DataRefManager:
    def __init__(
        self,
        registry: DataRefRegistry,
        xp: XPInterface,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._registry = registry
        self._xp = xp
        self.ready = False
        self._timeout = timeout_seconds
        self._start_time = time.time()

        if hasattr(xp, "bind_dataref_manager"):
            xp.bind_dataref_manager(self)

    def _notify_dataref_changed(self, handle: DataRefHandle) -> None:
        return None

    def try_bind_all(self) -> bool:
        if self.ready:
            return True

        elapsed = time.time() - self._start_time
        if elapsed > self._timeout:
            pid = self._xp.getMyID()
            self._xp.log(
                f"[DataRefManager] Timeout after {elapsed:.1f}s — disabling plugin {pid}"
            )
            self._xp.disablePlugin(pid)
            return False

        all_required = True
        for _, accessor in self._registry.items():
            if not accessor.try_bind() and accessor.spec.required:
                all_required = False

        if all_required:
            self.ready = True
            self._xp.log("[DataRefManager] All required datarefs bound")
            return True

        return False

    def ensure_datarefs(self) -> bool:
        if self.ready:
            return True
        return self.try_bind_all()
