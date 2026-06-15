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
import time
from threading import RLock
from typing import Any, Dict, Optional, TYPE_CHECKING

from simless.libs.fake_xp_types import FakeDataRef, ReadArray, ReadScalar, WriteArray, WriteScalar
from xp_typing import XPLMDataRef, XPLMDataTypeID

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class DataRefManager:
    """
    FakeXP DataRef backend subsystem using a single global lock.
    """

    _handles: Dict[str, FakeDataRef]  # all known datarefs
    _df_id_to_path: Dict[int, str]
    _handles_lock: RLock
    _next_df_id: int
    _next_owner_id: int

    def __init__(self, fake_xp: FakeXP) -> None:
        self.fake_xp = fake_xp

        self._handles = {}
        self._df_id_to_path = {}
        self._handles_lock = threading.RLock()
        self._next_df_id = 1
        self._next_owner_id = 1
        self._last_updated = time.monotonic()

    @property
    def last_updated(self) -> float:
        return self._last_updated

    # ----------------------------------------------------------------------
    # Default values for real xp.Type_* flags
    # ----------------------------------------------------------------------
    def default_value_for(self, dtype: int, size: int) -> Any:
        fxp = self.fake_xp

        # Arrays
        if dtype & fxp.Type_FloatArray:
            return [0.0] * size
        if dtype & fxp.Type_IntArray:
            return [0] * size
        if dtype & fxp.Type_Data:
            return bytearray(size)

        # Scalars
        if dtype & fxp.Type_Float:
            return 0.0
        if dtype & fxp.Type_Double:
            return 0.0
        if dtype & fxp.Type_Int:
            return 0

        return 0.0  # default

    # ----------------------------------------------------------------------
    # Handle management
    # ----------------------------------------------------------------------
    def get_handle(self, name: str) -> Optional[FakeDataRef]:
        """Return the FakeDataRef for the given path, or None."""
        with self._handles_lock:
            return self._handles.get(str(name))

    def require_handle(self, ref_id: XPLMDataRef) -> FakeDataRef:
        path = self._df_id_to_path.get(ref_id)
        if path is None or path not in self._handles:
            raise ValueError(f"Invalid handle: {ref_id}")
        return self._handles[path]

    def add_handle(
            self,
            name: str,
    ) -> FakeDataRef:
        """Register a new FakeDataRef handle."""

        ref = self._create_dummy(name)
        with self._handles_lock:
            self._handles[str(name)] = ref
            self._df_id_to_path[ref.df_id] = name
        self._last_updated = time.time()
        return ref

    def del_handle(self, ref_id: XPLMDataRef) -> None:
        """Delete a FakeDataRef handle."""
        path = self._df_id_to_path.get(ref_id)
        if path is None:
            return
        with self._handles_lock:
            del self._handles[path]
        self._last_updated = time.time()

    def all_handle_paths(self) -> list[str]:
        """Return a snapshot of all known DataRef handle paths."""
        with self._handles_lock:
            return list(self._handles.keys())

    def all_handles(self) -> list[FakeDataRef]:
        """Return a snapshot of all known DataRef handles."""
        with self._handles_lock:
            return list(self._handles.values())

    def _create_dummy(self, path: str) -> FakeDataRef:
        """
        Create a dummy DataRef with minimal information.
        Defaults to scalar float type, size=1, value=0.0.
        Dummy refs can change type until promoted
        """
        now = time.monotonic()
        ref = FakeDataRef(
            path=path,
            df_id=XPLMDataRef(self._next_df_id),
            type=self.fake_xp.Type_Float,
            writable=True,
            size=1,  # scalar
            value=0.0,

            read_scalar=None,
            write_scalar=None,
            read_array=None,
            write_array=None,
            read_refcon=None,
            write_refcon=None,

            dummy=True,
            last_modified=now
        )
        self._next_df_id += 1
        self._last_updated = now
        return ref

    def promote(
            self,
            ref: FakeDataRef,
            dtype: int,
            writable: bool,
            array_size: int,
            *,
            read_scalar: Optional[ReadScalar] = None,
            write_scalar: Optional[WriteScalar] = None,
            read_array: Optional[ReadArray] = None,
            write_array: Optional[WriteArray] = None,
            read_refcon: Any = None,
            write_refcon: Any = None,
    ) -> None:
        fxp = self.fake_xp
        old = ref.value

        # Accessor/dtype compatibility
        if dtype & (fxp.Type_FloatArray | fxp.Type_IntArray | fxp.Type_Data):
            if read_scalar or write_scalar:
                raise ValueError(f"{ref.path}: scalar accessors not allowed for array dtype")
        else:
            if read_array or write_array:
                raise ValueError(f"{ref.path}: array accessors not allowed for scalar dtype")

        # Determine if new definition is dynamic
        dynamic_new = (
                (dtype & fxp.Type_Data) or
                (read_array is not None) or
                (write_array is not None) or
                ((dtype & (fxp.Type_FloatArray | fxp.Type_IntArray)) and array_size == 0)
        )

        # array_size validation
        if dtype & (fxp.Type_FloatArray | fxp.Type_IntArray | fxp.Type_Data):
            if not dynamic_new and array_size <= 0:
                raise ValueError(f"{ref.path}: fixed arrays require array_size > 0")
        else:
            if array_size not in (0, 1):
                raise ValueError(f"{ref.path}: scalar types must have array_size 0 or 1")

        # No immutability: fixed arrays may change size now

        # Apply metadata
        ref.type = dtype
        ref.writable = writable
        ref.size = array_size

        # Install accessors
        if read_scalar is not None:
            ref.read_scalar = read_scalar
            ref.read_refcon = read_refcon
        if write_scalar is not None:
            ref.write_scalar = write_scalar
            ref.write_refcon = write_refcon

        if read_array is not None:
            ref.read_array = read_array
            ref.read_refcon = read_refcon
        if write_array is not None:
            ref.write_array = write_array
            ref.write_refcon = write_refcon

        # Allocate correct storage
        storage = self.default_value_for(dtype, array_size)
        ref.value = storage

        # Try to recast old value (never raise)
        try:
            if dtype & fxp.Type_Data:
                if isinstance(old, (bytes, bytearray, list, tuple)):
                    for i in range(min(array_size, len(old))):
                        storage[i] = int(old[i]) & 0xFF

            elif dtype & fxp.Type_FloatArray:
                if isinstance(old, (list, tuple)):
                    for i in range(min(array_size, len(old))):
                        storage[i] = float(old[i])

            elif dtype & fxp.Type_IntArray:
                if isinstance(old, (list, tuple)):
                    for i in range(min(array_size, len(old))):
                        storage[i] = int(old[i])

            elif dtype & (fxp.Type_Float | fxp.Type_Double):
                ref.value = float(old)

            elif dtype & fxp.Type_Int:
                ref.value = int(old)

        except Exception:
            pass  # incompatible → keep default

        # Finalize
        ref.dummy = False

    def get_value(
            self,
            ref: FakeDataRef,
            *,
            offset: int = 0,
            count: Optional[int] = None,
    ):
        """
        Unified read path for all DataRef reads.
        Returns:
          • scalar → Python value
          • array → list slice
        """
        fxp = self.fake_xp
        dtype = ref.type

        # -------------------------
        # Scalar read
        # -------------------------
        if ref.size == 1:
            self._require_scalar(ref, "get_value")

            # Accessor-backed?
            if ref.read_scalar:
                try:
                    return ref.read_scalar(ref.read_refcon)
                except Exception as e:
                    raise TypeError(f"{ref.path}: accessor read failed") from e

            v = ref.value

            if dtype & fxp.Type_Data:
                return int(v[0])
            if dtype & (fxp.Type_Float | fxp.Type_Double):
                return float(v)
            if dtype & fxp.Type_Int:
                return int(v)

            raise TypeError(f"{ref.path}: unsupported scalar dtype {dtype}")

        # -------------------------
        # Array read
        # -------------------------
        self._require_array(ref, "get_value")
        arr = ref.value

        if offset < 0:
            offset = 0

        if count is None or count < 0:
            count = len(arr) - offset

        if offset + count > len(arr):
            raise RuntimeError(f"{ref.path}: array read past end")

        # Accessor-backed?
        if ref.read_array:
            tmp = [0] * count
            try:
                got = int(ref.read_array(ref.read_refcon, tmp, offset, count))
            except Exception as e:
                raise TypeError(f"{ref.path}: accessor array read failed") from e
            return tmp[:got]

        # Canonical array read → return slice
        if dtype & fxp.Type_FloatArray:
            return [float(x) for x in arr[offset: offset + count]]

        if dtype & fxp.Type_IntArray:
            return [int(x) for x in arr[offset: offset + count]]

        if dtype & fxp.Type_Data:
            return arr[offset: offset + count]

        raise TypeError(f"{ref.path}: unsupported array dtype {dtype}")

    def update_value(
            self,
            ref: FakeDataRef,
            value: Any,
            *,
            offset: int = 0,
            count: Optional[int] = None
    ) -> None:
        """
        Minimal, strongly typed write path.
        Assumes promote() has already set dtype, shape, and storage.
        """
        fxp = self.fake_xp
        dtype = ref.type

        with self._handles_lock:
            if not ref.writable:
                raise ValueError(f"{ref.path}: DataRef not writable")

            # -------------------------
            # Scalar writes
            # -------------------------
            if not ref.is_array:
                if ref.write_scalar is not None:
                    try:
                        ref.write_scalar(ref.write_refcon, value)
                    except Exception:
                        raise ValueError(f"{ref.path}: accessor rejected scalar {value!r}")
                else:
                    if dtype & (fxp.Type_Float | fxp.Type_Double):
                        if not isinstance(value, (float, int)):
                            raise ValueError(f"{ref.path}: float scalar requires float")
                        ref.value = float(value)

                    elif dtype & fxp.Type_Int:
                        if not isinstance(value, int):
                            raise ValueError(f"{ref.path}: int scalar requires int")
                        ref.value = int(value)

                    elif dtype & fxp.Type_Data:
                        # single byte
                        try:
                            if isinstance(value, (bytes, bytearray)):
                                ref.value[0] = value[0] if value else 0
                            else:
                                ref.value[0] = int(value) & 0xFF
                        except Exception:
                            raise ValueError(f"{ref.path}: cannot cast {value!r} to byte")
                    else:
                        raise ValueError(f"{ref.path}: unsupported scalar dtype {dtype}")

                now = time.monotonic()
                ref.last_modified = now
                self._last_updated = now
                return

            # -------------------------
            # Array writes
            # -------------------------
            if count is None:
                try:
                    count = len(value)
                except Exception:
                    raise ValueError(f"{ref.path}: array update requires iterable")

            if offset < 0:
                raise ValueError(f"{ref.path}: negative offset invalid")
            if offset + count > ref.size:
                raise ValueError(f"{ref.path}: array write past end")

            if ref.write_array is not None:
                try:
                    ref.write_array(ref.write_refcon, value, offset, count)
                except Exception:
                    raise ValueError(f"{ref.path}: accessor rejected array write")
            else:
                arr = ref.value

                if dtype & fxp.Type_FloatArray:
                    if not isinstance(value, list) or not all(isinstance(x, (float, int)) for x in value):
                        raise ValueError(f"{ref.path}: FloatArray update requires list[float]")
                    for i in range(count):
                        arr[offset + i] = float(value[i])

                elif dtype & fxp.Type_IntArray:
                    if not isinstance(value, list) or not all(isinstance(x, int) for x in value):
                        raise ValueError(f"{ref.path}: IntArray update requires list[int]")
                    for i in range(count):
                        arr[offset + i] = int(value[i])

                elif dtype & fxp.Type_Data:
                    if isinstance(value, (bytes, bytearray)):
                        src = list(value)
                    elif isinstance(value, list) and all(isinstance(x, int) for x in value):
                        src = value
                    else:
                        raise ValueError(f"{ref.path}: DATA update requires bytes or list[int]")

                    if len(src) < count:
                        src = src + [0] * (count - len(src))

                    for i in range(count):
                        arr[offset + i] = src[i] & 0xFF
                else:
                    raise ValueError(f"{ref.path}: unsupported array dtype {dtype}")

            now = time.monotonic()
            ref.last_modified = now
            self._last_updated = now

    def shape_dummy(self, ref: FakeDataRef, dtype: XPLMDataTypeID | int, value: Optional[Any] = None) -> None:
        """
        Infer dummy shape/type from dataref API calls.
        """
        if not ref.dummy:
            raise ValueError("Cannot shape a canonical dataref")

        # Determine shaping value
        if value is None:
            dv = ref.value
            if ref.type != dtype:
                dv = self.default_value_for(dtype, 8)
        else:
            dv = value

        # Determine size
        size = 1
        if isinstance(dv, (list, tuple, bytearray)):
            size = len(dv)
            if not size:
                raise ValueError(f"Array is empty for {ref.path}")

        # Promote type + size
        if ref.type != dtype or ref.size != size:
            with self._handles_lock:
                ref.type = dtype
                ref.size = size
            # Delegate casting to update_value
            self.update_value(ref, dv)

    # ----------------------------------------------------------------------
    # Shape enforcement
    # ----------------------------------------------------------------------
    def _require_array(self, ref: FakeDataRef, api: str) -> None:
        """
        Enforce that array semantics are valid.
        Dummy refs may be array-shaped or scalar-shaped, but must match.
        """
        # Dummy: trust declared is_array
        if ref.dummy:
            if not ref.is_array:
                raise RuntimeError(f"{api} requires array-shaped dataRef")
            return

        # Accessor or canonical: must be array
        if not ref.is_array:
            raise RuntimeError(f"{api} requires array-shaped dataRef")

    def _require_scalar(self, ref: FakeDataRef, api: str) -> None:
        """
        Enforce that scalar semantics are valid.
        Dummy refs may be array-shaped or scalar-shaped, but must match.
        """
        # Dummy: trust declared is_array
        if ref.dummy:
            if ref.is_array:
                raise RuntimeError(f"{api} requires scalar-shaped dataRef")
            return

        # Accessor or canonical: must be scalar
        if ref.is_array:
            raise RuntimeError(f"{api} requires scalar-shaped dataRef")
