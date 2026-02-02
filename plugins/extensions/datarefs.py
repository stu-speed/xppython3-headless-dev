# ===========================================================================
# Managed dataRefs (Typed, Declarative, Deterministic)
#
# Provides a strongly‑typed, predictable dataref layer for XPPython3 plugins.
# Designed for deterministic startup and full simless (FakeXP) compatibility.
# Wait for required datarefs or use default value for optional datarefs until
# it becomes available.
#
# Components
# ---------------------------------------------------------------------------
# • DataRefSpec
#     Declarative definition of each dataref: path, dtype, writability,
#     required flag, and an optional default value.
#
# • DRefType
#     Enum describing supported X‑Plane dataref types.
#
# • TypedAccessor
#     Lazily binds datarefs and provides typed get()/set() operations.
#
# • DataRefRegistry
#     Central lookup for all accessors by logical name.
#
# • DataRefManager
#     Coordinates binding, enforces timeouts, and exposes ensure_datarefs()
#     for clean readiness checks. When running under FakeXP, it is
#     automatically bound so FakeXP can notify it on dataref writes.
#
# Default Values
# ---------------------------------------------------------------------------
# Defaults provide safe, typed values before binding, enable deterministic
# behavior in simless mode, support pre‑bind writes, and allow dtype inference.
# ===========================================================================

import time
from enum import Enum
from dataclasses import dataclass
from typing import Any

from .xp_interface import XPInterface


class DRefType(Enum):
    INT = "int"
    FLOAT = "float"
    DOUBLE = "double"
    INT_ARRAY = "int_array"
    FLOAT_ARRAY = "float_array"
    BYTE_ARRAY = "byte_array"


@dataclass
class DataRefSpec:
    path: str
    dtype: DRefType | None = None
    writable: bool | None = None
    description: str | None = None
    required: bool = True
    default: Any | None = None


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


class TypedAccessor:
    _handle: int | None

    def __init__(self, xp: XPInterface, spec: DataRefSpec) -> None:
        self._xp = xp
        self._spec = spec
        self._handle = None

    def try_bind(self) -> bool:
        if self._handle is not None:
            return True

        handle = self._xp.findDataRef(self._spec.path)
        self._handle = handle

        if handle is None:
            self._xp.log(f"[DataRef] Not found yet: {self._spec.path}")
            return False

        xp_type, writable, is_array, _ = self._xp.getDataRefInfo(handle)
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
            # Pre-bind write: update default so when bound, it starts with this value
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
            case _:
                raise TypeError(f"Unsupported dtype: {dtype}")


class DataRefRegistry:
    def __init__(self, xp: XPInterface, specs: dict[str, DataRefSpec]) -> None:
        self._xp = xp
        self._accessors = {
            name: TypedAccessor(xp, spec)
            for name, spec in specs.items()
        }

        # Auto-register for FakeXP (simless mode)
        for _, spec in specs.items():
            if hasattr(xp, "fake_register_dataref"):
                xp.fake_register_dataref(spec.path, spec.default, spec.writable)

    def __getitem__(self, name: str) -> TypedAccessor:
        return self._accessors[name]

    def items(self):
        return self._accessors.items()


class DataRefManager:
    """
    Manages binding and readiness of all datarefs.
    Provides ensure_datarefs() for clean plugin‑side readiness checks.

    When running under FakeXP, it is automatically bound so FakeXP can
    notify it on dataref writes via _notify_dataref_changed(). This keeps
    the design future‑proof if caching is added later, without forcing
    DataRefManager usage in simple simless plugins.
    """

    def __init__(self, registry: DataRefRegistry, xp: XPInterface, timeout_seconds: float = 30.0) -> None:
        self._registry = registry
        self._xp = xp
        self.ready: bool = False
        self._timeout = timeout_seconds
        self._start_time = time.time()

        # Optional binding for FakeXP so it can notify on writes
        if hasattr(xp, "bind_dataref_manager"):
            xp.bind_dataref_manager(self)

    def _notify_dataref_changed(self, handle: int) -> None:
        """
        Called by FakeXP when a dataref value changes.

        Currently a no-op because TypedAccessor.get() always reads directly
        from xp.* APIs. This hook exists to support future caching without
        changing FakeXP again.
        """
        # Placeholder for future cache invalidation logic.
        return None

    def try_bind_all(self) -> bool:
        if self.ready:
            return True

        elapsed = time.time() - self._start_time
        if elapsed > self._timeout:
            pid = self._xp.getMyID()
            self._xp.log(f"[DataRefManager] Timeout after {elapsed:.1f}s — disabling plugin {pid}")
            self._xp.disablePlugin(pid)
            return False

        all_required = True
        for _, accessor in self._registry.items():
            if not accessor.try_bind() and accessor._spec.required:
                all_required = False

        if all_required:
            self.ready = True
            self._xp.log("[DataRefManager] All required datarefs bound")
            return True

        return False

    def ensure_datarefs(self) -> bool:
        """Return True when all required datarefs are bound."""
        if self.ready:
            return True
        return self.try_bind_all()
