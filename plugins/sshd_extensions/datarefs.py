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

from sshd_extensions.xp_interface import XPInterface


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
    def __init__(self, xp: XPInterface, handle: Any, dtype: DRefType):
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
            size = xp.getDatavf(h, None, 0, 0)   # special gets int length
            out: list[float] = [0.0] * size
            xp.getDatavf(h, out, 0, size)
            return out
        if self._dtype == DRefType.INT_ARRAY:
            size = xp.getDatavi(h, None, 0, 0)   # special query gets int length
            out: list[int] = [0] * size
            xp.getDatavi(h, out, 0, size)
            return out
        if self._dtype == DRefType.BYTE_ARRAY:
            size = xp.getDatab(h, None, 0, 0)   # spe query gets int length
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

def _is_fake_xp(xp: XPInterface) -> bool:
    return hasattr(xp, "fake_register_dataref")


def _validate_datarefs(specs: Dict[str, DataRefSpec]) -> None:
    """
    Validate the declarative DataRefSpec dictionary before registry creation.
    Ensures dtype/default consistency, array sizing, and required‑field rules.
    Raises ValueError on any invalid specification.
    """

    for key, spec in specs.items():
        # --- path ---------------------------------------------------------
        if not isinstance(spec.path, str) or not spec.path.strip():
            raise ValueError(f"[DataRefs] '{key}': path must be a non‑empty string")

        # --- dtype --------------------------------------------------------
        if not isinstance(spec.dtype, DRefType):
            raise ValueError(f"[DataRefs] '{key}': dtype must be a DRefType enum")

        # --- required -----------------------------------------------------
        if spec.required and spec.default is None:
            raise ValueError(
                f"[DataRefs] '{key}': required=True but default=None; "
                "required DataRefs must define a default"
            )

        # --- dtype/default consistency -----------------------------------
        dt = spec.dtype
        default = spec.default

        # Scalar types
        if dt in (DRefType.INT, DRefType.FLOAT, DRefType.DOUBLE):
            if isinstance(default, (list, tuple, bytearray)):
                raise ValueError(
                    f"[DataRefs] '{key}': scalar dtype {dt.name} "
                    f"cannot have array default {default!r}"
                )
            if default is not None:
                try:
                    float(default)
                except Exception:
                    raise ValueError(
                        f"[DataRefs] '{key}': default {default!r} "
                        f"is not numeric for dtype {dt.name}"
                    )

        # Array types
        if dt in (DRefType.FLOAT_ARRAY, DRefType.INT_ARRAY, DRefType.BYTE_ARRAY):
            if default is None:
                raise ValueError(
                    f"[DataRefs] '{key}': array dtype {dt.name} requires a default list"
                )

            if not isinstance(default, (list, tuple, bytearray)):
                raise ValueError(
                    f"[DataRefs] '{key}': array dtype {dt.name} "
                    f"requires list/tuple/bytearray default, got {type(default)}"
                )

            if len(default) == 0:
                raise ValueError(
                    f"[DataRefs] '{key}': array default must have length ≥ 1"
                )

            # Element type checks
            if dt == DRefType.FLOAT_ARRAY:
                if not all(isinstance(x, (int, float)) for x in default):
                    raise ValueError(
                        f"[DataRefs] '{key}': FLOAT_ARRAY default must be numeric list"
                    )

            if dt == DRefType.INT_ARRAY:
                if not all(isinstance(x, int) for x in default):
                    raise ValueError(
                        f"[DataRefs] '{key}': INT_ARRAY default must be int list"
                    )

            if dt == DRefType.BYTE_ARRAY:
                if not isinstance(default, bytearray):
                    raise ValueError(
                        f"[DataRefs] '{key}': BYTE_ARRAY default must be bytearray"
                    )


class DataRefRegistry:
    """
    DataRefRegistry is responsible for:

      • Declaring all DataRefs from the plugin's spec dictionary
      • Auto‑registering DataRefs in FakeXP (with correct type + size)
      • Performing initial handle discovery in real X‑Plane
      • Exposing a public `handles` table for DataRefManager to use

    It does NOT perform binding or readiness checks — that is the
    responsibility of DataRefManager.
    """

    def __init__(self, xp, specs: Dict[str, DataRefSpec]):
        _validate_datarefs(specs)
        self.xp = xp
        self.specs = specs

        # Public handle table: key → handle or None
        self.handles: Dict[str, Any] = {}

        for key, spec in specs.items():
            xp_type = int(spec.dtype)
            is_array = spec.dtype in (
                DRefType.FLOAT_ARRAY,
                DRefType.INT_ARRAY,
                DRefType.BYTE_ARRAY,
            )

            # Determine array size (FakeXP requires this)
            size = 1
            if is_array and isinstance(spec.default, (list, tuple, bytearray)):
                size = len(spec.default)

            # FakeXP: create the dataref
            if _is_fake_xp(self.xp):
                handle = xp.fake_register_dataref(
                    spec.path,
                    xp_type=xp_type,
                    is_array=is_array,
                    size=size,
                    writable=spec.writable,
                )

            # Real X‑Plane: attempt to find the dataref
            else:
                handle = xp.findDataRef(spec.path)

            self.handles[key] = handle

    def accessor(self, key: str) -> TypedAccessor:
        """
        Convenience helper: return a TypedAccessor for a declared DataRef.
        This is used only for direct access, not for readiness binding.
        """
        spec = self.specs[key]
        handle = self.handles[key]
        return TypedAccessor(self.xp, handle, spec.dtype)


class DataRefManager:
    def __init__(
        self,
        specs: Dict[str, DataRefSpec],
        xp: XPInterface,
        timeout_seconds: float = 10.0,
    ):
        """
        DataRefManager receives only the declarative DataRefSpec dictionary.
        It internally constructs a DataRefRegistry so FakeXP can auto‑register
        datarefs and real X‑Plane can perform initial handle discovery.
        """

        self.specs = specs
        self.xp = xp
        self.timeout = timeout_seconds

        # Create registry internally (FakeXP auto‑registers here)
        self.registry = DataRefRegistry(xp, specs)

        # Bound TypedAccessor objects
        self._bound: Dict[str, TypedAccessor] = {}

        if _is_fake_xp(self.xp):
            xp.bind_dataref_manager(self)

    def __getitem__(self, name: str) -> TypedAccessor:
        return self.registry.accessor(name)

    def _notify_dataref_changed(self, ref: Any) -> None:
        path = getattr(ref, "path", None)
        if not path:
            return

        for key, spec in self.specs.items():
            if spec.path == path:
                acc = self._bound.get(key)
                if acc is not None:
                    acc.invalidate()

    def ready(self, counter: int) -> bool:
        """
        Determine whether all managed DataRefs are bound and safe to use.

        This is called from the plugin's flight loop. X‑Plane may expose
        DataRefs several frames after plugin load, especially during aircraft
        reloads or when other plugins register DataRefs late.
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
        if len(self._bound) == len(self.specs):
            return True

        try:
            for key, spec in self.specs.items():
                if key in self._bound:
                    continue

                handle = self.registry.handles[key]

                # Retry findDataRef if missing
                if not handle:
                    new_handle = self.xp.findDataRef(spec.path)
                    if not new_handle:
                        break
                    self.registry.handles[key] = new_handle
                    handle = new_handle

                info = self.xp.getDataRefInfo(handle)
                if info is None:
                    self.xp.log(f"[DRM] ERROR: getDataRefInfo failed for {spec.path}")
                    break

                xp_type = getattr(info, "xp_type", getattr(info, "type", None))
                if xp_type != int(spec.dtype):
                    self.xp.log(
                        f"[DRM] ERROR: type mismatch for {spec.path} "
                        f"(got {xp_type}, expected {int(spec.dtype)})"
                    )
                    break

                # Bind accessor
                self._bound[key] = TypedAccessor(self.xp, handle, spec.dtype)

            # If still not fully bound, check timeout
            if len(self._bound) != len(self.specs):
                elapsed = counter - self._start_counter

                # Emit a warning once per minute
                if elapsed > self.timeout and (counter - self._last_warn_counter) >= 60:
                    self.xp.log(
                        f"[DRM] WARNING: Required DataRefs not ready after "
                        f"{elapsed} seconds; still waiting..."
                    )
                    self._last_warn_counter = counter

                # Hard timeout: disable plugin
                if elapsed > self.timeout:
                    plugin_id = self.xp.getMyID()
                    self.xp.log(
                        f"[DRM] ERROR: Required DataRefs not available after "
                        f"{self.timeout} seconds — disabling plugin."
                    )
                    self.xp.disablePlugin(plugin_id)
                    return False

                return False

            return True

        except Exception as exc:
            self.xp.log(f"[DRM] ERROR: Exception in ready(): {exc!r}")
            return False
