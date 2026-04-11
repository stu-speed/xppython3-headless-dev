# simless/libs/fake_xp_dataref.py
# =======================================================================
# FakeXP DataRef subsystem — xp_typing-backed implementation
#
# CORE INVARIANTS
#   • Public API signatures MUST MATCH real X‑Plane / XPPython3.
#   • FakeDataRef is the single authoritative value store.
#
# PRINCIPLES
#   • Single handle type: FakeDataRef returned by findDataRef.
#   • Dummy-first: findDataRef creates a dummy (is_dummy=True) so plugins get
#     a handle immediately; runner/bridge promotes it later.
#   • setters can reshape dummy datarefs as they are formed with a default.
#   • In-place promotion: promote_handle flips is_dummy -> False and updates
#     metadata on the same object.
#   • Single global lock: one RLock protects _handles and all handle state.
#   • Subsystem-composed: FakeXP binds only declared public API names.
#
# ARRAY SEMANTICS
#   • Dummy handles: array writes replace the backing buffer (elastic placeholder).
#   • Real handles: array writes update in-place and enforce bounds (production parity).
#   • Array getters: `offset` is the destination buffer offset (XPLM semantics).
# =======================================================================

from __future__ import annotations

import threading
from threading import RLock
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from PythonPlugins.sshd_extensions.dataref_manager import DRefType
from simless.libs.fake_xp_types import (
    FakeDataRef, Type_Data, Type_Double, Type_Float, Type_FloatArray, Type_Int,
    Type_IntArray, Type_Unknown
)

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class DataRefManager:
    """
    FakeXP DataRef subsystem using a single global lock.

    IMPORTANT:
      • Do NOT implement __init__ in this subsystem class.
      • FakeXP composes subsystems and calls `_init_dataref()` during initialization.
      • This subsystem explicitly declares the FakeXP API endpoints it exposes.
        FakeXP must bind ONLY these names onto the xp facade.
    """

    _handle_callback: Optional[Callable[[FakeDataRef], None]]
    _handles: Dict[str, FakeDataRef]
    # accessor metadata for registered accessors (name -> metadata)
    _accessors: Dict[str, Dict[str, Any]]
    # single global lock protecting _handles and all handle state
    _handles_lock: RLock
    # simple owner id counter for registered accessors
    _next_owner_id: int

    def __init__(self, fake_xp: FakeXP) -> None:
        self.fake_xp = fake_xp

        self._handles: Dict[str, FakeDataRef] = {}
        self._accessors: Dict[str, Dict[str, Any]] = {}
        self._handle_callback = None
        self._handles_lock = threading.RLock()
        self._next_owner_id = 1

    @staticmethod
    def default_value_for(dtype: DRefType, size: int):
        if dtype == DRefType.FLOAT_ARRAY:
            return [0.0] * size
        if dtype == DRefType.INT_ARRAY:
            return [0] * size
        if dtype == DRefType.BYTE_ARRAY:
            return bytearray(size)
        if dtype in (DRefType.FLOAT, DRefType.DOUBLE):
            return 0.0
        if dtype == DRefType.INT:
            return 0
        raise TypeError(f"Unsupported DRefType: {dtype}")

    @staticmethod
    def dreftype_to_bitmask(dtype: DRefType, is_array: Optional[bool]) -> int:
        """
        Map internal DRefType + observed shape to XPLM bitmask.

        If shape is unknown (is_array is None), return Type_Unknown.
        """
        if is_array is None:
            return Type_Unknown

        if is_array:
            if dtype == DRefType.FLOAT_ARRAY:
                return Type_FloatArray
            if dtype == DRefType.INT_ARRAY:
                return Type_IntArray
            if dtype == DRefType.BYTE_ARRAY:
                return Type_Data
            return Type_Unknown
        else:
            if dtype == DRefType.FLOAT:
                return Type_Float
            if dtype == DRefType.DOUBLE:
                return Type_Double
            if dtype == DRefType.INT:
                return Type_Int
            return Type_Unknown

    def notify_handle_created(self, ref: FakeDataRef) -> None:
        # read callback under lock, but invoke it outside to avoid deadlocks
        with self._handles_lock:
            cb = self._handle_callback
        if cb is None:
            return
        try:
            # noinspection PyCallingNonCallable
            cb(ref)
        except Exception:
            self.fake_xp.log(f"[FakeXP] handle callback raised for {ref.path}")

    def require_array(self, ref: FakeDataRef, api: str) -> None:
        # Dummy refs have no authoritative shape — allow provisional arrays
        if ref.is_dummy:
            if not ref.is_array:
                raise RuntimeError(f"{api} requires array-shaped dataRef")
            return

        # Real refs must have authoritative shape
        if not ref.shape_known or not ref.is_array:
            raise RuntimeError(
                f"{api} requires array-shaped dataRef (shape not known or scalar)"
            )

    def require_scalar(self, ref: FakeDataRef, api: str) -> None:
        """
        Enforce that scalar semantics are currently valid.
        """

        # Dummy refs: allow provisional scalar behavior
        if ref.is_dummy:
            if getattr(ref, "is_array", False):
                raise RuntimeError(f"{api} requires scalar-shaped dataRef")
            return

        # Real refs: require authoritative scalar shape
        if getattr(ref, "shape_known", False) and getattr(ref, "is_array", None) is True:
            raise RuntimeError(
                f"{api} requires scalar-shaped dataRef (currently array)"
            )

    # -------------------------
    # Callback management
    # -------------------------
    def attach_handle_callback(self, cb: Optional[Callable[[FakeDataRef], None]]) -> None:
        """Register a single synchronous callback invoked when a handle is created. Passing None clears it."""
        with self._handles_lock:
            self._handle_callback = cb

    def detach_handle_callback(self) -> None:
        with self._handles_lock:
            self._handle_callback = None

    # -------------------------
    # Dummy update and promotion helpers
    # -------------------------

    def get_handle(self, name: str) -> Optional[FakeDataRef]:
        name_str = str(name)
        with self._handles_lock:
            return self._handles.get(name_str)

    def add_handle(self, name: str, ref: FakeDataRef) -> None:
        with self._handles_lock:
            name_str = str(name)
            self._handles[name_str] = ref

    def del_handle(self, name) -> None:
        with self._handles_lock:
            name_str = str(name)
            del self._handles[name_str]

    def all_handle_paths(self) -> list[str]:
        """Return a snapshot of all known DataRef handle paths."""
        with self._handles_lock:
            return list(self._handles.keys())

    def all_handles(self) -> list[FakeDataRef]:
        """Return a snapshot of all known DataRef handles."""
        with self._handles_lock:
            return list(self._handles.values())

    def promote_type(
        self,
        ref: FakeDataRef,
        dtype: DRefType,
        writable: bool,
    ) -> None:
        """
        Promote type authority for an existing handle.

        This method is called when authoritative metadata (META) is received.
        It establishes numeric type and writability, and coerces the stored
        value to match the promoted type.

        Semantics:
          • Promotion is in-place; the FakeDataRef object is preserved.
          • Scalar ↔ array transitions are allowed:
                – Scalar → array wraps the scalar into a length‑1 array and casts.
                – Array → scalar takes the first element and casts.
          • Array → array and scalar → scalar transitions cast elements or the scalar.
          • Array attributes (is_array, array_size) are updated to match the coerced value.
          • No shape inference is performed; scalar → array always produces size 1.
          • Incompatible or uncastable values fall back to a default value.
          • Idempotent: safe to call multiple times with the same dtype.

        Raises:
          • TypeError if ref is invalid
        """

        if ref is None:
            raise TypeError("invalid dataRef")

        with self._handles_lock:
            ref.type = dtype
            ref.writable = bool(writable)

            try:
                v = ref.value

                # --- ARRAY TARGET TYPES ---
                if dtype in (DRefType.FLOAT_ARRAY, DRefType.INT_ARRAY, DRefType.BYTE_ARRAY):
                    if isinstance(v, (list, bytearray)):
                        # Array → array: cast elements
                        if dtype == DRefType.FLOAT_ARRAY:
                            newv = [float(x) for x in v]
                        elif dtype == DRefType.INT_ARRAY:
                            newv = [int(x) for x in v]
                        else:
                            newv = bytearray(v)
                    else:
                        # Scalar → array: wrap scalar into length‑1 array
                        if dtype == DRefType.FLOAT_ARRAY:
                            newv = [float(v)]
                        elif dtype == DRefType.INT_ARRAY:
                            newv = [int(v)]
                        else:
                            newv = bytearray([int(v) & 0xFF])

                    ref.value = newv
                    ref.is_array = True
                    ref.size = len(newv)

                # --- SCALAR TARGET TYPES ---
                else:
                    if isinstance(v, (list, bytearray)):
                        # Array → scalar: take first element and cast
                        first = v[0] if len(v) else 0
                        if dtype in (DRefType.FLOAT, DRefType.DOUBLE):
                            newv = float(first)
                        elif dtype == DRefType.INT:
                            newv = int(first)
                        else:
                            newv = self.default_value_for(dtype, 1)
                    else:
                        # Scalar → scalar: cast normally
                        if dtype in (DRefType.FLOAT, DRefType.DOUBLE):
                            newv = float(v)
                        elif dtype == DRefType.INT:
                            newv = int(v)
                        else:
                            newv = self.default_value_for(dtype, 1)

                    ref.value = newv
                    ref.is_array = False
                    ref.size = 1

            except (TypeError, ValueError):
                # Fallback: default scalar or array of size 1
                dv = self.default_value_for(dtype, 1)
                ref.value = dv
                ref.is_array = isinstance(dv, (list, bytearray))
                ref.size = len(dv) if ref.is_array else 1

            ref.type_known = True

    def promote_shape_from_value(
        self,
        ref: FakeDataRef,
        value: Any,
    ) -> None:
        """
        Promote shape authority for an existing handle using an authoritative value.

        This method is called on the first real provider UPDATE.
        The provided value is authoritative for both shape and storage.

        Semantics:
          • Promotion is in-place; the FakeDataRef object is preserved.
          • Shape (scalar vs array) and size are inferred from the value.
          • Existing dummy values are discarded unconditionally.
          • Storage is allocated to exactly match the value shape.
          • Idempotent: safe to call multiple times.

        Raises:
          • TypeError if ref is invalid
        """
        if ref is None:
            raise TypeError("invalid dataRef")
        if ref.shape_known:
            return

        with self._handles_lock:
            if isinstance(value, (list, tuple, bytearray)):
                ref.is_array = True
                ref.size = len(value)

                if ref.type == DRefType.BYTE_ARRAY:
                    ref.value = bytearray(value)
                elif ref.type == DRefType.FLOAT_ARRAY:
                    ref.value = [float(x) for x in value]
                elif ref.type == DRefType.INT_ARRAY:
                    ref.value = [int(x) for x in value]
                else:
                    raise TypeError("array value incompatible with scalar type")
            else:
                ref.is_array = False
                ref.size = 1

                if ref.type in (DRefType.FLOAT, DRefType.DOUBLE):
                    ref.value = float(value)
                elif ref.type == DRefType.INT:
                    ref.value = int(value)
                else:
                    ref.value = self.default_value_for(ref.type, 1)

            ref.shape_known = True

    def conform_dummy_to_value(
        self,
        ref: FakeDataRef,
        value,
        offset: int = 0,
        count: int | None = None,
    ) -> None:
        if ref is None:
            raise TypeError("invalid dataRef")

        if not ref.is_dummy:
            return

        # ------------------------------------------------------------
        # Normalize array intent
        # ------------------------------------------------------------
        is_array_write = offset != 0 or isinstance(value, (list, tuple, bytearray))

        if isinstance(value, (list, tuple, bytearray)):
            if count is None or count < 0:
                count = len(value)
            sample = value[0] if value else 0
        else:
            count = 1
            sample = value

        # ------------------------------------------------------------
        # Determine provisional type
        # ------------------------------------------------------------
        if isinstance(sample, float):
            dtype = DRefType.FLOAT_ARRAY if is_array_write else DRefType.FLOAT
        elif isinstance(sample, int):
            dtype = DRefType.INT_ARRAY if is_array_write else DRefType.INT
        elif isinstance(sample, (bytes, bytearray)):
            dtype = DRefType.BYTE_ARRAY
            is_array_write = True
        else:
            raise TypeError(f"unsupported DataRef value type: {type(sample)}")

        ref.type = dtype

        # ------------------------------------------------------------
        # Scalar write
        # ------------------------------------------------------------
        if not is_array_write:
            ref.is_array = False
            ref.size = 1
            ref.value = float(value) if dtype == DRefType.FLOAT else int(value)
            return

        # ------------------------------------------------------------
        # Array write
        # ------------------------------------------------------------
        needed = offset + count
        ref.is_array = True
        ref.size = max(ref.size or 0, needed)

        if dtype == DRefType.FLOAT_ARRAY:
            if not isinstance(ref.value, list):
                ref.value = [0.0] * needed
            elif len(ref.value) < needed:
                ref.value.extend([0.0] * (needed - len(ref.value)))
            for i in range(count):
                ref.value[offset + i] = float(value[i])

        elif dtype == DRefType.INT_ARRAY:
            if not isinstance(ref.value, list):
                ref.value = [0] * needed
            elif len(ref.value) < needed:
                ref.value.extend([0] * (needed - len(ref.value)))
            for i in range(count):
                ref.value[offset + i] = int(value[i])

        elif dtype == DRefType.BYTE_ARRAY:
            if not isinstance(ref.value, bytearray):
                ref.value = bytearray(needed)
            elif len(ref.value) < needed:
                ref.value.extend([0] * (needed - len(ref.value)))
            for i in range(count):
                ref.value[offset + i] = int(value[i]) & 0xFF
