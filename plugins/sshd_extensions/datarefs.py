# plugins/sshd_extensions/datarefs.py
# ===========================================================================
# DataRefs — unified production/simless DataRef layer
#
# ROLE
#   Provide a deterministic, typed, validation‑driven interface for all
#   DataRef metadata and value access. This subsystem is the authoritative
#   source of truth for DataRef shape, readiness, writability, and type
#   correctness. It remains independent of X‑Plane transport concerns.
#
# ENVIRONMENT RULES
#   • In PRODUCTION:
#         Each plugin may instantiate its own DataRefManager. Instances are
#         independent and simply wrap the X‑Plane SDK’s global DataRef system.
#
#   • In SIMLESS:
#         All plugins must transparently share a single DataRefManager bound
#         to the FakeXP instance. This preserves the production invariant of
#         “one simulator → one DataRef namespace” while allowing plugins to
#         instantiate DataRefManager normally.
#
#   • No plugin code changes are required. DataRefManager detects whether the
#     xp interface already has a bound manager and reuses it automatically.
#
# CORE INVARIANTS
#   - DataRefSpec is the canonical metadata representation.
#   - DataRefManager owns all validation, readiness tracking, and value access.
#   - No other subsystem may infer or validate DataRef metadata.
#   - Required DataRefs enforce readiness timeouts.
#   - Optional DataRefs never block readiness.
#   - get_value() returns raw X‑Plane values without coercion.
#   - set_value() enforces dtype, array_size, and writability.
#
# SINGLETON RULE (SIMLESS ONLY)
#   - If xp already has a _dataref_manager attribute, DataRefManager.__new__()
#     returns that instance instead of creating a new one.
#   - Production xp objects do not have this attribute, so each plugin gets
#     its own independent manager.
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional, Iterable

from XPPython3.xp_typing import XPLMDataRef, XPLMDataRefInfo_t


# ===========================================================================
# DRefType — production enum (mirrors X‑Plane SDK)
# ===========================================================================
class DRefType(IntEnum):
    INT         = 1
    FLOAT       = 2
    DOUBLE      = 4
    FLOAT_ARRAY = 8
    INT_ARRAY   = 16
    BYTE_ARRAY  = 32


# ===========================================================================
# DataRefSpec — canonical metadata representation
# ===========================================================================

@dataclass(slots=True)
class DataRefSpec:
    """
    Canonical DataRef specification.

    Shape is expressed via:
      • array_size = 0 for scalars
      • array_size = N (>0) for arrays
    """
    name: str
    type: int
    writable: bool

    required: bool = False
    default: Any = None

    handle: Optional[XPLMDataRef] = None
    is_dummy: bool = False

    array_size: int = 0  # 0 = scalar, >0 = array length

    # ------------------------------------------------------------------
    # Internal validator
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_array_size(path: str, dtype: int, array_size: int) -> int:
        array_size = int(array_size)

        if dtype in (
            int(DRefType.FLOAT_ARRAY),
            int(DRefType.INT_ARRAY),
            int(DRefType.BYTE_ARRAY),
        ):
            if array_size <= 0:
                raise ValueError(
                    f"DataRef '{path}' is array type ({dtype}) but array_size={array_size}"
                )
        else:
            if array_size != 0:
                raise ValueError(
                    f"DataRef '{path}' is scalar type ({dtype}) but array_size={array_size}"
                )

        return array_size

    # ------------------------------------------------------------------
    # Construction from real metadata
    # ------------------------------------------------------------------
    @classmethod
    def from_info(
        cls,
        path: str,
        info: XPLMDataRefInfo_t,
        required: bool,
        default: Any,
        handle: Optional[XPLMDataRef],
        is_dummy: bool,
        array_size: Optional[int] = None,
    ) -> "DataRefSpec":
        dtype = info.type

        if array_size is None:
            if dtype in (
                int(DRefType.FLOAT),
                int(DRefType.INT),
                int(DRefType.DOUBLE),
            ):
                array_size = 0
            else:
                raise ValueError(
                    f"DataRef '{path}' is array type ({dtype}) but no array_size was provided"
                )

        array_size = cls._validate_array_size(path, dtype, array_size)

        return cls(
            name=path,
            type=dtype,
            writable=info.writable,
            required=required,
            default=default,
            handle=handle,
            is_dummy=is_dummy,
            array_size=array_size,
        )

    # ------------------------------------------------------------------
    # Dummy spec
    # ------------------------------------------------------------------
    @classmethod
    def dummy(cls, path: str, *, required: bool, default: Any) -> "DataRefSpec":
        if isinstance(default, (list, bytes, bytearray)):
            array_size = len(default)
        else:
            array_size = 0

        return cls(
            name=path,
            type=int(DRefType.FLOAT),
            writable=False,
            required=required,
            default=default,
            handle=None,
            is_dummy=True,
            array_size=array_size,
        )

    # ------------------------------------------------------------------
    # Promotion from dummy → real
    # ------------------------------------------------------------------
    def promote(
        self,
        handle: XPLMDataRef,
        info: XPLMDataRefInfo_t,
        array_size: Optional[int],
    ) -> None:
        self.handle = handle
        self.is_dummy = False

        dtype = info.type
        self.type = dtype
        self.writable = info.writable

        if array_size is None:
            if dtype in (
                int(DRefType.FLOAT),
                int(DRefType.INT),
                int(DRefType.DOUBLE),
            ):
                array_size = 0
            else:
                raise ValueError(
                    f"DataRef '{self.name}' is array type ({dtype}) but no array_size provided during promote()"
                )

        array_size = self._validate_array_size(self.name, dtype, array_size)
        self.array_size = array_size

        # XP initializes DataRefs to zero; align defaults
        self.default = [0.0] * array_size if array_size > 0 else 0.0


# ===========================================================================
# DataRefManager — authoritative DataRef lifecycle manager
# ===========================================================================
class DataRefManager:
    """
    Unified DataRef manager for production and simless.

    PRODUCTION:
        Each plugin may instantiate its own DataRefManager. Instances are
        independent wrappers around the global X‑Plane DataRef system.

    SIMLESS:
        All plugins share a single DataRefManager bound to the FakeXP
        instance. Plugins still instantiate DataRefManager normally, but
        __new__ returns the shared instance.
    """

    # ------------------------------------------------------------------
    # Singleton-per-XP-instance (simless only)
    # ------------------------------------------------------------------
    def __new__(cls, xp, *args, **kwargs):
        existing = getattr(xp, "_dataref_manager", None)
        if existing is not None:
            return existing

        instance = super().__new__(cls)
        setattr(xp, "_dataref_manager", instance)
        return instance

    # ------------------------------------------------------------------
    # Initialization after new
    # ------------------------------------------------------------------
    def __init__(
        self,
        xp: Any,
        datarefs: Optional[Dict[Any, Dict[str, Any]]] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        """
        __init__ may run multiple times if plugins instantiate repeatedly.
        In simless, __new__ ensures a shared instance, so __init__ must:
          - initialize core state only once
          - ALWAYS merge new specs
          - ALWAYS update timeout conservatively (max)
        """

        # --------------------------------------------------------------
        # First-time initialization
        # --------------------------------------------------------------
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self.xp = xp
            self.specs: Dict[str, DataRefSpec] = {}
            self._all_real = True
            self._start_counter: Optional[int] = None

            # Bind to XP if supported (production)
            if hasattr(self.xp, "bind_dataref_manager"):
                self.xp.bind_dataref_manager(self)

            # Initial timeout
            self.timeout = timeout_seconds
        else:
            # ----------------------------------------------------------
            # Subsequent __init__ calls (simless)
            # Timeout must be conservative: keep the maximum
            # ----------------------------------------------------------
            self.timeout = max(self.timeout, timeout_seconds)

        # --------------------------------------------------------------
        # Merge passed-in specs (append behavior)
        # --------------------------------------------------------------
        if datarefs:
            for path, cfg in datarefs.items():
                required = cfg.get("required", False)
                default = cfg.get("default", None)

                if path not in self.specs:
                    # New dummy spec
                    self.specs[path] = DataRefSpec.dummy(
                        path,
                        required=required,
                        default=default,
                    )
                    self._all_real = False
                else:
                    # Existing spec — update fields if provided
                    spec = self.specs[path]
                    if "required" in cfg:
                        spec.required = required
                    if "default" in cfg:
                        spec.default = default

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add_spec(self, path: str, spec: DataRefSpec) -> None:
        self.specs[path] = spec

    def get_spec(self, path: str) -> Optional[DataRefSpec]:
        return self.specs.get(path)

    # ------------------------------------------------------------------
    # Value retrieval
    # ------------------------------------------------------------------
    def get_value(self, path: str) -> Any:
        spec = self.specs.get(path)
        if spec is None:
            return None

        if spec.is_dummy or spec.handle is None:
            return spec.default

        xp = self.xp
        h = spec.handle
        t = spec.type

        if t == int(DRefType.FLOAT):
            return xp.getDataf(h)
        if t == int(DRefType.INT):
            return xp.getDatai(h)
        if t == int(DRefType.DOUBLE):
            return xp.getDatad(h)
        if t == int(DRefType.FLOAT_ARRAY):
            size = xp.getDatavf(h, None, 0, 0)
            out = [0.0] * size
            xp.getDatavf(h, out, 0, size)
            return out
        if t == int(DRefType.INT_ARRAY):
            size = xp.getDatavi(h, None, 0, 0)
            out = [0] * size
            xp.getDatavi(h, out, 0, size)
            return out
        if t == int(DRefType.BYTE_ARRAY):
            size = xp.getDatab(h, None, 0, 0)
            out = bytearray(size)
            xp.getDatab(h, out, 0, size)
            return out

        raise TypeError(f"Unsupported dtype {t}")

    # ------------------------------------------------------------------
    # Value write
    # ------------------------------------------------------------------
    def set_value(self, path: str, value: Any) -> None:
        spec = self.specs.get(path)
        if spec is None:
            raise KeyError(f"Unknown DataRef '{path}'")

        if spec.is_dummy or spec.handle is None:
            raise RuntimeError(f"DataRef '{path}' is not ready; cannot set value")

        if not spec.writable:
            raise PermissionError(f"DataRef '{path}' is not writable")

        xp = self.xp
        h = spec.handle
        t = spec.type

        # Scalars
        if t == int(DRefType.FLOAT):
            if not isinstance(value, (int, float)):
                raise TypeError(f"Expected float for '{path}'")
            xp.setDataf(h, float(value))
            return

        if t == int(DRefType.INT):
            if not isinstance(value, (int, float)):
                raise TypeError(f"Expected int for '{path}'")
            xp.setDatai(h, int(value))
            return

        if t == int(DRefType.DOUBLE):
            if not isinstance(value, (int, float)):
                raise TypeError(f"Expected double for '{path}'")
            xp.setDatad(h, float(value))
            return

        # Arrays
        if t == int(DRefType.FLOAT_ARRAY):
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"Expected list[float] for '{path}'")
            if len(value) != spec.array_size:
                raise ValueError(
                    f"Array size mismatch for '{path}': expected {spec.array_size}, got {len(value)}"
                )
            xp.setDatavf(h, value, 0, spec.array_size)
            return

        if t == int(DRefType.INT_ARRAY):
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"Expected list[int] for '{path}'")
            if len(value) != spec.array_size:
                raise ValueError(
                    f"Array size mismatch for '{path}': expected {spec.array_size}, got {len(value)}"
                )
            xp.setDatavi(h, value, 0, spec.array_size)
            return

        if t == int(DRefType.BYTE_ARRAY):
            if not isinstance(value, (bytes, bytearray)):
                raise TypeError(f"Expected bytes/bytearray for '{path}'")
            if len(value) != spec.array_size:
                raise ValueError(
                    f"Array size mismatch for '{path}': expected {spec.array_size}, got {len(value)}"
                )
            xp.setDatab(h, value, 0, spec.array_size)
            return

        raise TypeError(f"Unsupported dtype {t}")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    def all_paths(self) -> Iterable[str]:
        return self.specs.keys()

    def clear(self) -> None:
        self.specs.clear()
        self._start_counter = None
        self._all_real = True

    # ------------------------------------------------------------------
    # Startup resolution
    # ------------------------------------------------------------------
    def ready(self, counter: int) -> bool:
        if self._all_real:
            return True

        if self._start_counter is None:
            self._start_counter = counter
            return False

        all_real = True

        for path, spec in list(self.specs.items()):
            if not spec.is_dummy:
                continue

            handle = self.xp.findDataRef(path)
            if handle is None:
                all_real = False
                continue

            info = self.xp.getDataRefInfo(handle)

            t = info.type
            if t == int(DRefType.FLOAT_ARRAY):
                array_size = self.xp.getDatavf(handle, None, 0, 0)
            elif t == int(DRefType.INT_ARRAY):
                array_size = self.xp.getDatavi(handle, None, 0, 0)
            elif t == int(DRefType.BYTE_ARRAY):
                array_size = self.xp.getDatab(handle, None, 0, 0)
            else:
                array_size = 0

            spec.promote(handle, info, array_size)

        if all_real:
            self._all_real = True
            return True

        elapsed = counter - self._start_counter
        if elapsed > self.timeout:
            missing = [
                p for p, s in self.specs.items()
                if s.is_dummy and s.required
            ]
            if missing:
                self.xp.log(
                    f"[DRM] ERROR: Required DataRefs not available after "
                    f"{self.timeout} seconds: {missing}"
                )
                self.xp.disablePlugin(self.xp.getMyID())
            return False

        return False
