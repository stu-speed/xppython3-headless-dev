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
from typing import Any, Dict

from XPPython3 import xp

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
            size = xp.getDatavf(h, None, 0, 0)   # query length
            out: list[float] = [0.0] * size
            xp.getDatavf(h, out, 0, size)
            return out
        if self._dtype == DRefType.INT_ARRAY:
            size = xp.getDatavi(h, None, 0, 0)   # query length
            out: list[int] = [0] * size
            xp.getDatavi(h, out, 0, size)
            return out
        if self._dtype == DRefType.BYTE_ARRAY:
            size = xp.getDatab(h, None, 0, 0)    # query length
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
# FakeXP detection
# ======================================================================

def _is_fake_xp(xp):
    return hasattr(xp, "fake_register_dataref")


# ======================================================================
# DataRefRegistry — plugin‑side declaration + FakeXP auto‑registration
# ======================================================================

class DataRefRegistry:
    def __init__(self, xp, specs: Dict[str, DataRefSpec]):
        self._xp = xp
        self._specs = specs
        self._handles: Dict[str, Any] = {}

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

            if _is_fake_xp(self._xp):
                handle = xp.fake_register_dataref(
                    spec.path,
                    xp_type=xp_type,
                    is_array=is_array,
                    size=size,
                    writable=spec.writable,
                )
            else:
                handle = xp.findDataRef(spec.path)

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

        if _is_fake_xp(self._xp):
            xp.bind_dataref_manager(self)

    def ready(self, counter: int) -> bool:
        """
        Determine whether all managed DataRefs are bound and safe to use.

        This readiness check is only required when a plugin uses DataRefManager.
        X‑Plane may expose DataRefs several frames after plugin load, especially
        during aircraft reloads or when other plugins register DataRefs late.

        We retry binding incrementally until all required DataRefs are available.
        If binding does not complete within the configured timeout, the plugin is
        disabled to avoid running in a partially initialized state.
        """

        # Validation call: never ready on counter 0
        if counter == 0:
            self._start_counter = counter
            self._last_warn_counter = counter
            return False

        # Initialize counters on first real call
        if not hasattr(self, "_start_counter"):
            self._start_counter = counter
            self._last_warn_counter = counter

        # Fast path: already bound
        if len(self._bound) == len(self._registry._specs):
            return True

        try:
            for key, spec in self._registry._specs.items():
                if key in self._bound:
                    continue

                handle = self._registry._handles[key]

                # Retry findDataRef if missing
                if not handle:
                    new_handle = self._xp.findDataRef(spec.path)
                    if not new_handle:
                        break  # still missing; check timeout below
                    self._registry._handles[key] = new_handle
                    handle = new_handle

                info = self._xp.getDataRefInfo(handle)
                if info is None:
                    xp.log(f"[DRM] ERROR: getDataRefInfo failed for {spec.path}")
                    break

                if info.type != int(spec.dtype):
                    xp.log(
                        f"[DRM] ERROR: type mismatch for {spec.path} "
                        f"(got {info.type}, expected {int(spec.dtype)})"
                    )
                    break

                # Bind accessor
                self._bound[key] = TypedAccessor(self._xp, handle, spec.dtype)

            # If still not fully bound, check timeout
            if len(self._bound) != len(self._registry._specs):
                elapsed = counter - self._start_counter

                # Emit a warning once per minute
                if elapsed > self._timeout and (counter - self._last_warn_counter) >= 60:
                    xp.log(
                        f"[DRM] WARNING: Required DataRefs not ready after "
                        f"{elapsed} seconds; still waiting..."
                    )
                    self._last_warn_counter = counter

                # Hard timeout: disable plugin
                if elapsed > self._timeout:
                    plugin_id = self._xp.getMyID()
                    xp.log(
                        f"[DRM] ERROR: Required DataRefs not available after "
                        f"{self._timeout} seconds — disabling plugin."
                    )
                    self._xp.disablePlugin(plugin_id)
                    return False

                return False

            return True

        except Exception as exc:
            xp.log(f"[DRM] ERROR: Exception in ready(): {exc!r}")
            return False
