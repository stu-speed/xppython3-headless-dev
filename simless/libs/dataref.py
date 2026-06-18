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
from typing import Any, Dict, Optional, Sequence, TYPE_CHECKING

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
        self._last_updated = time.monotonic()

        cache_info = self.fake_xp.dataref_cache.get_cached_info(ref.path)
        if cache_info is not None:
            self.promote(ref, dtype=cache_info.type, writable=cache_info.writable, array_size=cache_info.size,
                         cached=True)
            self.update_value(ref.df_id, ref.type, cache_info.value)
        if cache_info is None:
            print("hello")

        return ref

    def del_handle(self, ref_id: XPLMDataRef) -> None:
        """Delete a FakeDataRef handle."""
        path = self._df_id_to_path.get(ref_id)
        if path is None:
            return
        with self._handles_lock:
            del self._handles[path]
        self._last_updated = time.monotonic()

    def all_handle_paths(self) -> list[str]:
        """Return a snapshot of all known DataRef handle paths."""
        with self._handles_lock:
            return list(self._handles.keys())

    def all_handles(self) -> list[FakeDataRef]:
        """Return a snapshot of all known DataRef handles."""
        with self._handles_lock:
            return list(self._handles.values())

    def mark_modified(self, ref: FakeDataRef) -> None:
        now = time.monotonic()
        ref.last_modified = now
        self._last_updated = now

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
            cached=False,
            last_modified=now
        )
        self._next_df_id += 1
        return ref

    def promote(
            self,
            ref: FakeDataRef,
            dtype: int,
            writable: bool,
            cached: bool = False,
            array_size: Optional[int] = None,
            read_scalar: Optional[ReadScalar] = None,
            write_scalar: Optional[WriteScalar] = None,
            read_array: Optional[ReadArray] = None,
            write_array: Optional[WriteArray] = None,
            read_refcon: Optional[object] = None,
            write_refcon: Optional[object] = None,
    ) -> None:
        """
        Promote a dummy DataRef to authoritative metadata and optional accessors.

        • Promotion is only legal when ``ref.dummy`` is True.
        • Accessor installation must NOT overwrite canonical storage.
        • Canonical storage is allocated ONLY when the type changes.
        • Promotion performs no writes; UPDATE will set the real value.
        """

        # ------------------------------------------------------------
        # 0. Allow repromotes
        # ------------------------------------------------------------
        if not ref.dummy:
            self.fake_xp.log(f"Re-promoting dataref {ref.path}")

        # ------------------------------------------------------------
        # 1. Install accessor callbacks (never allocate storage here)
        # ------------------------------------------------------------
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

        # ------------------------------------------------------------
        # 2. Compute new size BEFORE updating metadata
        # ------------------------------------------------------------
        if dtype in (self.fake_xp.Type_IntArray, self.fake_xp.Type_FloatArray, self.fake_xp.Type_Data):
            if array_size is None or array_size < 0:
                raise ValueError(f"{ref.path}: array promotion requires size")
            new_size: int = array_size
        else:
            new_size = 1

        # ------------------------------------------------------------
        # 3. Allocate storage ONLY if the type changes
        # ------------------------------------------------------------
        if ref.type != dtype:
            ref.value = self.default_value_for(dtype, new_size)

        # ------------------------------------------------------------
        # 4. Update metadata
        # ------------------------------------------------------------
        with self._handles_lock:
            ref.type = dtype
            ref.writable = writable
            ref.size = new_size
            ref.dummy = False
            ref.cached = cached

    def get_value(
            self,
            dr: XPLMDataRef,
            desired_type: XPLMDataTypeID | int,
            offset: int = 0,
            count: int = -1,
            values: Optional[list] = None,
    ):
        fxp = self.fake_xp

        # ------------------------------------------------------------
        # 0. Resolve ref
        # ------------------------------------------------------------
        ref = self.require_handle(dr)

        # ------------------------------------------------------------
        # 1. Dummy shaping or type validation
        # ------------------------------------------------------------
        if ref.dummy:
            self.shape_dummy(
                ref,
                desired_type,
                value=values,
                offset=offset,
                count=count,
            )
        else:
            if not self._is_compatible(ref.type, desired_type):
                raise TypeError(
                    f"{ref.path}: expected type {desired_type}, "
                    f"but DataRef is promoted as {ref.type}"
                )

        ref_type = ref.type

        # ============================================================
        # 2. SCALAR REQUEST (desired_type is scalar)
        # ============================================================
        if desired_type in (fxp.Type_Float, fxp.Type_Int, fxp.Type_Double):

            # Underlying scalar
            if not ref.is_array:
                if ref.read_scalar:
                    try:
                        v = ref.read_scalar(ref.read_refcon)
                    except Exception as e:
                        raise TypeError(f"{ref.path}: accessor read failed") from e
                else:
                    v = ref.value

            # Underlying array → take element 0
            else:
                if ref.read_array:
                    tmp = [0]
                    try:
                        ref.read_array(ref.read_refcon, tmp, 0, 1)
                    except Exception as e:
                        raise TypeError(f"{ref.path}: accessor array read failed") from e
                    v = tmp[0]
                else:
                    v = ref.value[0]

            # Normalize scalar to desired type
            if desired_type == fxp.Type_Float:
                v = float(v)
            elif desired_type == fxp.Type_Int:
                v = int(v)
            elif desired_type == fxp.Type_Double:
                v = float(v)

            # Write into caller buffer?
            if values is not None:
                values.clear()
                values.append(v)
                return 1

            return v

        # ============================================================
        # 3. ARRAY REQUEST (desired_type is array)
        # ============================================================

        # Scalar → array conversion
        if not ref.is_array:
            if ref.read_scalar:
                try:
                    v = ref.read_scalar(ref.read_refcon)
                except Exception as e:
                    raise TypeError(f"{ref.path}: accessor read failed") from e
            else:
                v = ref.value

            # Convert scalar → array of length 1
            if desired_type == fxp.Type_FloatArray:
                arr = [float(v)]
            elif desired_type == fxp.Type_IntArray:
                arr = [int(v)]
            else:
                raise TypeError(f"{ref.path}: unsupported array desired_type {desired_type}")

            if values is not None:
                values.clear()
                values.extend(arr)
            return 1

        # Underlying is array
        arr = ref.value
        size = len(arr)

        # Normalize offset/count
        if offset < 0:
            offset = 0
        if count < 0:
            count = size - offset

        # Accessor-backed array
        if ref.read_array:
            tmp = [0] * count
            try:
                got = int(ref.read_array(ref.read_refcon, tmp, offset, count))
            except Exception as e:
                raise TypeError(f"{ref.path}: accessor array read failed") from e

            if values is not None:
                values.clear()
                values.extend(tmp[:got])

            return got

        # Canonical array
        if offset >= size:
            if values is not None:
                values.clear()
            return 0

        count = min(count, size - offset)
        slice_ = arr[offset: offset + count]

        # Normalize array to desired type
        if desired_type == fxp.Type_FloatArray:
            result = [float(x) for x in slice_]
        elif desired_type == fxp.Type_IntArray:
            result = [int(x) for x in slice_]
        else:
            result = slice_

        if values is not None:
            values.clear()
            values.extend(result)

        return len(result)

    def update_value(
            self,
            dr: XPLMDataRef,
            expected_type: int,
            value: Any,
            offset: int = 0,
            count: int = -1,
    ) -> int:
        """
        Universal XPPython3‑accurate write path.

        Responsibilities:
          • resolve ref
          • shape dummy refs using expected_type
          • validate type for promoted refs
          • scalar:
                - accessor-backed → write_scalar()
                - canonical → cast+store
          • array:
                - accessor-backed → write_array()
                - canonical numeric → clip
                - canonical DATA → strict bounds
          • return semantics:
                scalar → None
                array  → number of elements written
        """
        ref = self.require_handle(dr)

        if not ref.writable:
            raise ValueError(f"{ref.path}: writable=False")

        # ------------------------------------------------------------
        # 1. Dummy shaping or type validation
        # ------------------------------------------------------------
        if ref.dummy:
            inferred_count = (
                len(value)
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
                else 1
            )
            self.shape_dummy(
                ref,
                expected_type,
                value=value,
                offset=offset,
                count=inferred_count,
            )
        else:
            if ref.type != expected_type:
                raise TypeError(
                    f"{ref.path}: expected type {expected_type}, "
                    f"but DataRef is promoted as {ref.type}"
                )

        dtype = ref.type
        self.mark_modified(ref)

        # ------------------------------------------------------------
        # 2. SCALAR WRITE
        # ------------------------------------------------------------
        if not ref.is_array:
            # Accessor-backed scalar
            if ref.write_scalar:
                try:
                    ref.write_scalar(ref.write_refcon, value)
                except Exception:
                    raise ValueError(f"{ref.path}: accessor rejected scalar {value!r}")
                return ref.size

            # Canonical scalar
            self._canonical_scalar_write(ref, dtype, value)
            return ref.size

        # ------------------------------------------------------------
        # 3. ARRAY WRITE
        # ------------------------------------------------------------

        # Accessor-backed array
        if ref.write_array:
            # XPPython3 rule: caller must supply at least count values
            if count < 0:
                count = len(value)
            if len(value) < count:
                raise ValueError(f"{ref.path}: list too short for provided count")

            # Accessor does its own bounds checking
            try:
                ref.write_array(ref.write_refcon, value, offset, count)
            except Exception:
                raise ValueError(f"{ref.path}: accessor rejected array write")
            return count

        # ------------------------------------------------------------
        # 4. CANONICAL ARRAY WRITE
        # ------------------------------------------------------------
        size = ref.size

        # Determine count
        if count < 0:
            try:
                count = len(value)
            except Exception:
                raise ValueError(f"{ref.path}: array update requires iterable")

        # DATA arrays: strict bounds
        if dtype & self.fake_xp.Type_Data:
            if offset < 0 or offset + count > size:
                raise ValueError(f"{ref.path}: DATA write past end of buffer")

            buf = ref.value
            if isinstance(value, (bytes, bytearray)):
                src = list(value)
            elif isinstance(value, list) and all(isinstance(x, int) for x in value):
                src = value
            else:
                raise ValueError(f"{ref.path}: DATA update requires bytes or list[int]")

            # Pad with zeros if src is shorter than count
            if len(src) < count:
                src = src + [0] * (count - len(src))

            for i in range(count):
                buf[offset + i] = src[i] & 0xFF

            return count

        # Numeric arrays: clip
        n = max(0, min(count, size - offset))

        if n == 0:
            return 0

        arr = ref.value

        if dtype & self.fake_xp.Type_FloatArray:
            for i in range(n):
                arr[offset + i] = float(value[i])

        elif dtype & self.fake_xp.Type_IntArray:
            for i in range(n):
                arr[offset + i] = int(value[i])

        else:
            raise ValueError(f"{ref.path}: unsupported array dtype {dtype}")

        return n

    def shape_dummy(
            self,
            ref: FakeDataRef,
            dtype: int,
            value: Optional[Any] = None,
            offset: int = 0,
            count: int = -1,
    ) -> None:
        """
        Infer dummy shape/type from dtype and optional value (from setData)
        Dummy arrays expand dynamically based on offset + count.
        Existing values are preserved; new slots are filled with defaults.
        """

        if not ref.dummy:
            raise ValueError("Cannot shape a canonical dataref")

        if ref.type != dtype:
            ref.value = self.default_value_for(dtype, 1)

        dv = ref.value if value is None else value

        new_size = 1
        if isinstance(dv, (list, tuple, bytearray)):
            if count < 1:
                count = len(dv)
            new_size = max(offset + count, ref.size)

        # If same shape, do nothing
        if ref.type == dtype and ref.size == new_size:
            return

        # ------------------------------------------------------------
        # 3. Recast type + size and expand array if needed
        # ------------------------------------------------------------
        with self._handles_lock:
            ref.type = dtype
            ref.size = new_size

            # Get default for array type (list)
            default_list = self.default_value_for(dtype, 1)

            # Extract scalar element for expansion
            if isinstance(default_list, (list, tuple, bytearray)):
                default = default_list[0] if default_list else 0
            else:
                default = default_list

            if ref.is_array:
                # Expand array while preserving existing values
                if isinstance(ref.value, list):
                    while len(ref.value) < new_size:
                        ref.value.append(default)
                else:
                    # Convert scalar dummy to array
                    ref.value = [default] * new_size
            else:
                # SCALAR: ensure value is scalar
                if isinstance(ref.value, list):
                    ref.value = ref.value[0] if ref.value else default

            self.mark_modified(ref)

    def _canonical_scalar_write(self, ref, dtype, value) -> None:
        fxp = self.fake_xp

        if dtype & (fxp.Type_Float | fxp.Type_Double):
            if not isinstance(value, (float, int)):
                raise ValueError(f"{ref.path}: float scalar requires float")
            ref.value = float(value)

        elif dtype & fxp.Type_Int:
            if not isinstance(value, int):
                raise ValueError(f"{ref.path}: int scalar requires int")
            ref.value = int(value)

        elif dtype & fxp.Type_Data:
            try:
                if isinstance(value, (bytes, bytearray)):
                    ref.value[0] = value[0] if value else 0
                else:
                    ref.value[0] = int(value) & 0xFF
            except Exception:
                raise ValueError(f"{ref.path}: cannot cast {value!r} to byte")

        else:
            raise ValueError(f"{ref.path}: unsupported scalar dtype {dtype}")

    def _canonical_array_write(self, ref, dtype, value, offset, count) -> int:
        fxp = self.fake_xp

        if count is None or count < 0:
            try:
                count = len(value)
            except Exception:
                raise ValueError(f"{ref.path}: array update requires iterable")

        if offset < 0:
            raise ValueError(f"{ref.path}: negative offset invalid")

        size = ref.size

        if offset >= size:
            raise ValueError(f"{ref.path}: array write offset past end")

        n = min(count, size - offset)
        arr = ref.value

        # FLOAT ARRAY
        if dtype & fxp.Type_FloatArray:
            if not isinstance(value, list) or not all(isinstance(x, (float, int)) for x in value):
                raise ValueError(f"{ref.path}: FloatArray update requires list[float]")
            for i in range(n):
                arr[offset + i] = float(value[i])

        # INT ARRAY
        elif dtype & fxp.Type_IntArray:
            if not isinstance(value, list) or not all(isinstance(x, int) for x in value):
                raise ValueError(f"{ref.path}: IntArray update requires list[int]")
            for i in range(n):
                arr[offset + i] = int(value[i])

        # DATA ARRAY
        elif dtype & fxp.Type_Data:
            if isinstance(value, (bytes, bytearray)):
                src = list(value)
            elif isinstance(value, list) and all(isinstance(x, int) for x in value):
                src = value
            else:
                raise ValueError(f"{ref.path}: DATA update requires bytes or list[int]")

            if len(src) < n:
                src = src + [0] * (n - len(src))

            for i in range(n):
                arr[offset + i] = src[i] & 0xFF

        else:
            raise ValueError(f"{ref.path}: unsupported array dtype {dtype}")

        return n

    def _is_compatible(self, ref_type: int, desired_type: int) -> bool:
        fxp = self.fake_xp

        # ------------------------------------------------------------
        # 1. Direct bitmask compatibility
        # ------------------------------------------------------------
        if (ref_type & desired_type) != 0:
            return True

        # ------------------------------------------------------------
        # 2. Array → scalar (FloatArray→Float, IntArray→Int)
        # ------------------------------------------------------------
        if (ref_type & fxp.Type_FloatArray) and (desired_type & fxp.Type_Float):
            return True
        if (ref_type & fxp.Type_IntArray) and (desired_type & fxp.Type_Int):
            return True

        # ------------------------------------------------------------
        # 3. Array → scalar (cross‑type)
        #    FloatArray → Int
        #    IntArray   → Float
        # ------------------------------------------------------------
        if (ref_type & fxp.Type_FloatArray) and (desired_type & fxp.Type_Int):
            return True
        if (ref_type & fxp.Type_IntArray) and (desired_type & fxp.Type_Float):
            return True

        # ------------------------------------------------------------
        # 4. Scalar → array (Float→FloatArray, Int→IntArray)
        # ------------------------------------------------------------
        if (ref_type & fxp.Type_Float) and (desired_type & fxp.Type_FloatArray):
            return True
        if (ref_type & fxp.Type_Int) and (desired_type & fxp.Type_IntArray):
            return True

        # ------------------------------------------------------------
        # 5. Scalar → array (cross‑type)
        #    Float → IntArray
        #    Int   → FloatArray
        # ------------------------------------------------------------
        if (ref_type & fxp.Type_Float) and (desired_type & fxp.Type_IntArray):
            return True
        if (ref_type & fxp.Type_Int) and (desired_type & fxp.Type_FloatArray):
            return True

        return False

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
