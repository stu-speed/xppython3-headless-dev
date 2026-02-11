# plugins/sshd_extensions/datarefs.py
# ===========================================================================
# DataRefs — unified production/simless DataRef layer (PRODUCTION ONLY)
#
# ROLE
#   Provide a deterministic, typed, validation‑driven interface for all
#   DataRef metadata and value access. This subsystem is the authoritative
#   source of truth for DataRef shape, readiness, writability, and type
#   correctness. It must remain independent of X‑Plane transport concerns.
#
# ENVIRONMENT RULE
#   This file is PRODUCTION‑ONLY.
#   Simless must never import this module. FakeXPDataRef provides the
#   simless‑only DataRef engine.
#
# CORE INVARIANTS
#   - DataRefSpec is the canonical representation of a DataRef.
#   - DataRefManager owns all validation, readiness tracking, and value
#     retrieval semantics.
#   - No other subsystem may infer or validate DataRef metadata.
#   - No dummy DataRefs are created unless explicitly requested.
#   - No mutation of X‑Plane SDK objects; normalization happens here.
#
# METADATA RULES
#   - DataRefSpec.from_info() receives:
#         path, info, required, default, handle, is_dummy, array_size
#   - array_size must be validated exclusively by _validate_array_size().
#   - array_size=0 denotes scalar; >0 denotes array.
#   - dtype, writable, and array_size must be internally consistent.
#
# VALIDATION RULES
#   - All type, array, and writability checks occur inside DataRefSpec.
#   - DataRefManager must reject invalid specs immediately.
#   - Required DataRefs must enforce readiness timeouts.
#   - Optional DataRefs must never block readiness.
#
# VALUE ACCESS RULES
#   - get_value() returns raw X‑Plane values without coercion.
#   - Arrays must match array_size exactly.
#   - Scalars must be Python primitives.
#
# READINESS RULES
#   - A DataRef is ready when:
#         • handle is valid
#         • metadata is validated
#         • value retrieval succeeds
#   - ready(counter) returns True only when all required DataRefs are ready
#     or have timed out.
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
    Unified DataRef specification.

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
        """
        Enforce scalar/array rules:

          • Scalar types → array_size must be 0
          • Array types  → array_size must be > 0
        """
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
        """
        Build a spec from a real XPLMDataRefInfo_t-like object.
        """
        dtype = info.type

        # Determine array_size
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
        """
        Dummy spec used before X‑Plane provides the real DataRef.
        Type/shape inferred from defaults; later promoted via promote().
        """
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
        """
        Promote a dummy spec to a real, bound DataRef using explicit array_size.
        """
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
        if array_size > 0:
            self.default = [0.0] * array_size
        else:
            self.default = 0.0


# ===========================================================================
# DataRefManager — authoritative DataRef lifecycle manager
# ===========================================================================
class DataRefManager:
    """
    Unified DataRef manager for production and simless.

    PRODUCTION‑ONLY:
      This module must never be imported by simless. FakeXPDataRef provides
      the simless DataRef engine. The only simless interaction allowed is
      optional binding via xp.bind_dataref_manager().
    """

    def __init__(
        self,
        xp: Any,
        datarefs: Optional[Dict[Any, Dict[str, Any]]] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.xp = xp
        self.timeout = timeout_seconds
        self._start_counter: Optional[int] = None

        self.specs: Dict[str, DataRefSpec] = {}
        self._all_real: bool = True

        # Optional: allow FakeXP to bind for simless defaults
        if hasattr(self.xp, "bind_dataref_manager"):
            self.xp.bind_dataref_manager(self)

        # Initialize dummy specs if provided
        if datarefs:
            self._all_real = False
            for path, cfg in datarefs.items():
                required = cfg.get("required", False)
                default = cfg.get("default", None)
                self.specs[path] = DataRefSpec.dummy(
                    path,
                    required=required,
                    default=default,
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add_spec(self, path: str, spec: DataRefSpec) -> None:
        self.specs[path] = spec

    def get_spec(self, path: str) -> Optional[DataRefSpec]:
        return self.specs.get(path)

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
        """
        Bind all declared DataRefs once, using xp.findDataRef + xp.getDataRefInfo.
        """
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

            # Compute array_size explicitly
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

        # Timeout
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
