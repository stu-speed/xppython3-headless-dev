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

from simless.libs.fake_xp_types import FakeDataRef

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
    _accessors: Dict[str, Dict[str, Any]]
    _handles_lock: RLock
    _next_owner_id: int

    def __init__(self, fake_xp: FakeXP) -> None:
        self.fake_xp = fake_xp

        self._handles = {}
        self._accessors = {}
        self._handle_callback = None
        self._handles_lock = threading.RLock()
        self._next_owner_id = 1

    # ----------------------------------------------------------------------
    # Default values for real xp.Type_* flags
    # ----------------------------------------------------------------------
    def default_value_for(self, dtype: int, size: int):
        """
        Return a default value appropriate for the given xp.Type_* dtype.
        """
        fxp = self.fake_xp

        if dtype == fxp.Type_FloatArray:
            return [0.0] * size
        if dtype == fxp.Type_IntArray:
            return [0] * size
        if dtype == fxp.Type_Data:
            return bytearray(size)
        if dtype in (fxp.Type_Float, fxp.Type_Double):
            return 0.0
        if dtype == fxp.Type_Int:
            return 0
        raise TypeError(f"Unsupported xp.Type_* dtype: {dtype}")

    # ----------------------------------------------------------------------
    # Convert dtype + shape → real XPLM bitmask
    # ----------------------------------------------------------------------
    def dtype_to_bitmask(self, dtype: int) -> int:
        """
        Map a single concrete dtype to the XPLM type bitmask.
        This mirrors X-Plane: the DataRef has one true type,
        and the mask expresses API capabilities.
        """
        fxp = self.fake_xp

        # Scalar numeric types
        if dtype == fxp.Type_Int:
            return fxp.Type_Int
        if dtype == fxp.Type_Float:
            return fxp.Type_Float
        if dtype == fxp.Type_Double:
            return fxp.Type_Double

        # Array types
        if dtype == fxp.Type_IntArray:
            return fxp.Type_IntArray
        if dtype == fxp.Type_FloatArray:
            return fxp.Type_FloatArray
        if dtype == fxp.Type_Data:
            return fxp.Type_Data

        return fxp.Type_Unknown

    def is_array_type(self, dtype: int) -> bool:
        fxp = self.fake_xp
        return dtype in (
            fxp.Type_FloatArray,
            fxp.Type_IntArray,
            fxp.Type_Data,
        )

    def is_array_shape(self, ref: FakeDataRef) -> bool:
        """
        True if the DataRef is currently behaving as an array.
        For dummy refs, this reflects provisional behavior.
        For real refs, this reflects authoritative shape.
        """
        if ref.is_dummy:
            # Provisional behavior only
            return bool(ref.is_array)

        # Authoritative shape
        return ref.shape_known and ref.is_array is True

    # ----------------------------------------------------------------------
    # Callback notification
    # ----------------------------------------------------------------------
    def notify_handle_created(self, ref: FakeDataRef) -> None:
        """
        Notify the registered callback (if any) that a new handle was created.
        """
        with self._handles_lock:
            cb = self._handle_callback
        if cb:
            try:
                # noinspection PyCallingNonCallable
                cb(ref)
            except Exception:
                self.fake_xp.log(f"[FakeXP] handle callback raised for {ref.path}")

    # ----------------------------------------------------------------------
    # Shape enforcement
    # ----------------------------------------------------------------------
    def require_array(self, ref: FakeDataRef, api: str) -> None:
        """
        Enforce that array semantics are currently valid.
        """
        if ref.is_dummy:
            if not ref.is_array:
                raise RuntimeError(f"{api} requires array-shaped dataRef")
            return

        if not ref.shape_known or not ref.is_array:
            raise RuntimeError(f"{api} requires array-shaped dataRef")

    def require_scalar(self, ref: FakeDataRef, api: str) -> None:
        """
        Enforce that scalar semantics are currently valid.
        """
        if ref.is_dummy:
            if getattr(ref, "is_array", False):
                raise RuntimeError(f"{api} requires scalar-shaped dataRef")
            return

        if getattr(ref, "shape_known", False) and getattr(ref, "is_array", None) is True:
            raise RuntimeError(f"{api} requires scalar-shaped dataRef")

    # ----------------------------------------------------------------------
    # Callback management
    # ----------------------------------------------------------------------
    def attach_handle_callback(self, cb: Optional[Callable[[FakeDataRef], None]]) -> None:
        """Register a synchronous callback invoked when a handle is created."""
        with self._handles_lock:
            self._handle_callback = cb

    def detach_handle_callback(self) -> None:
        """Remove the handle-created callback."""
        with self._handles_lock:
            self._handle_callback = None

    # ----------------------------------------------------------------------
    # Handle management
    # ----------------------------------------------------------------------
    def get_handle(self, name: str) -> Optional[FakeDataRef]:
        """Return the FakeDataRef for the given path, or None."""
        with self._handles_lock:
            return self._handles.get(str(name))

    def add_handle(self, name: str, ref: FakeDataRef) -> None:
        """Register a new FakeDataRef handle."""
        with self._handles_lock:
            self._handles[str(name)] = ref

    def del_handle(self, name) -> None:
        """Delete a FakeDataRef handle."""
        with self._handles_lock:
            del self._handles[str(name)]

    def all_handle_paths(self) -> list[str]:
        """Return a snapshot of all known DataRef handle paths."""
        with self._handles_lock:
            return list(self._handles.keys())

    def all_handles(self) -> list[FakeDataRef]:
        """Return a snapshot of all known DataRef handles."""
        with self._handles_lock:
            return list(self._handles.values())

    # ----------------------------------------------------------------------
    # Type promotion (pure xp.Type_* flags)
    # ----------------------------------------------------------------------
    def promote_type(self, ref: FakeDataRef, dtype: int, writable: bool) -> None:
        """
        Promote type authority for an existing handle.

        Semantics:
          • Promotion is in-place.
          • Scalar ↔ array transitions are allowed.
          • Values are cast appropriately.
          • Idempotent.
        """
        if ref is None:
            raise TypeError("invalid dataRef")

        fxp = self.fake_xp

        with self._handles_lock:
            ref.type = dtype
            ref.writable = bool(writable)

            try:
                v = ref.value

                # --- ARRAY TARGET TYPES ---
                if dtype in (fxp.Type_FloatArray, fxp.Type_IntArray, fxp.Type_Data):
                    if isinstance(v, (list, bytearray)):
                        if dtype == fxp.Type_FloatArray:
                            newv = [float(x) for x in v]
                        elif dtype == fxp.Type_IntArray:
                            newv = [int(x) for x in v]
                        else:
                            newv = bytearray(v)
                    else:
                        if dtype == fxp.Type_FloatArray:
                            newv = [float(v)]
                        elif dtype == fxp.Type_IntArray:
                            newv = [int(v)]
                        else:
                            newv = bytearray([int(v) & 0xFF])

                    ref.value = newv
                    ref.is_array = True
                    ref.size = len(newv)

                # --- SCALAR TARGET TYPES ---
                else:
                    if isinstance(v, (list, bytearray)):
                        first = v[0] if len(v) else 0
                        if dtype in (fxp.Type_Float, fxp.Type_Double):
                            newv = float(first)
                        elif dtype == fxp.Type_Int:
                            newv = int(first)
                        else:
                            newv = self.default_value_for(dtype, 1)
                    else:
                        if dtype in (fxp.Type_Float, fxp.Type_Double):
                            newv = float(v)
                        elif dtype == fxp.Type_Int:
                            newv = int(v)
                        else:
                            newv = self.default_value_for(dtype, 1)

                    ref.value = newv
                    ref.is_array = False
                    ref.size = 1

            except (TypeError, ValueError):
                dv = self.default_value_for(dtype, 1)
                ref.value = dv
                ref.is_array = isinstance(dv, (list, bytearray))
                ref.size = len(dv) if ref.is_array else 1

            ref.type_known = True

    # ----------------------------------------------------------------------
    # Shape promotion
    # ----------------------------------------------------------------------
    def promote_shape_from_value(self, ref: FakeDataRef, value: Any) -> None:
        """
        Promote shape authority for an existing handle using an authoritative value.
        """
        if ref is None:
            raise TypeError("invalid dataRef")
        if ref.shape_known:
            return

        fxp = self.fake_xp

        with self._handles_lock:
            if isinstance(value, (list, tuple, bytearray)):
                ref.is_array = True
                ref.size = len(value)

                if ref.type == fxp.Type_Data:
                    ref.value = bytearray(value)
                elif ref.type == fxp.Type_FloatArray:
                    ref.value = [float(x) for x in value]
                elif ref.type == fxp.Type_IntArray:
                    ref.value = [int(x) for x in value]
                else:
                    raise TypeError("array value incompatible with scalar type")

            else:
                ref.is_array = False
                ref.size = 1

                if ref.type in (fxp.Type_Float, fxp.Type_Double):
                    ref.value = float(value)
                elif ref.type == fxp.Type_Int:
                    ref.value = int(value)
                else:
                    ref.value = self.default_value_for(ref.type, 1)

            ref.shape_known = True

    # ----------------------------------------------------------------------
    # Dummy → real conformance
    # ----------------------------------------------------------------------
    def conform_dummy_to_value(self, ref: FakeDataRef, value, offset: int = 0, count: int | None = None) -> None:
        """
        Conform a dummy FakeDataRef to the shape and type implied by a write.
        """
        if ref is None:
            raise TypeError("invalid dataRef")
        if not ref.is_dummy:
            return

        fxp = self.fake_xp

        is_array_write = offset != 0 or isinstance(value, (list, tuple, bytearray))

        if isinstance(value, (list, tuple, bytearray)):
            if count is None or count < 0:
                count = len(value)
            sample = value[0] if value else 0
        else:
            count = 1
            sample = value

        # Determine provisional dtype
        if isinstance(sample, float):
            dtype = fxp.Type_FloatArray if is_array_write else fxp.Type_Float
        elif isinstance(sample, int):
            dtype = fxp.Type_IntArray if is_array_write else fxp.Type_Int
        elif isinstance(sample, (bytes, bytearray)):
            dtype = fxp.Type_Data
            is_array_write = True
        else:
            raise TypeError(f"unsupported DataRef value type: {type(sample)}")

        ref.type = dtype

        # Scalar write
        if not is_array_write:
            ref.is_array = False
            ref.size = 1
            ref.value = float(value) if dtype == fxp.Type_Float else int(value)
            return

        # Array write
        needed = offset + count
        ref.is_array = True
        ref.size = max(ref.size or 0, needed)

        if dtype == fxp.Type_FloatArray:
            if not isinstance(ref.value, list):
                ref.value = [0.0] * needed
            elif len(ref.value) < needed:
                ref.value.extend([0.0] * (needed - len(ref.value)))
            for i in range(count):
                ref.value[offset + i] = float(value[i])

        elif dtype == fxp.Type_IntArray:
            if not isinstance(ref.value, list):
                ref.value = [0] * needed
            elif len(ref.value) < needed:
                ref.value.extend([0] * (needed - len(ref.value)))
            for i in range(count):
                ref.value[offset + i] = int(value[i])

        elif dtype == fxp.Type_Data:
            if not isinstance(ref.value, bytearray):
                ref.value = bytearray(needed)
            elif len(ref.value) < needed:
                ref.value.extend([0] * (needed - len(ref.value)))
            for i in range(count):
                ref.value[offset + i] = int(value[i]) & 0xFF
