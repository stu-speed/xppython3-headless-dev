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

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, MutableSequence, Sequence, Callable, Tuple
import threading
import copy

from XPPython3.xp_typing import XPLMDataRefInfo_t
from sshd_extensions.dataref_manager import DRefType
from simless.libs.fake_xp_interface import FakeXPInterface

# XPLM data type bitmask constants
Type_Unknown = 0
Type_Int = 1
Type_Float = 2
Type_Double = 4
Type_FloatArray = 8
Type_IntArray = 16
Type_Data = 32

_ARRAY_DREFTYPES = {DRefType.FLOAT_ARRAY, DRefType.INT_ARRAY, DRefType.BYTE_ARRAY}


@dataclass(slots=True)
class FakeDataRef:
    path: str
    type: DRefType
    writable: bool
    size: int
    value: Any
    is_dummy: bool = False

    @property
    def is_array(self) -> bool:
        return self.type in _ARRAY_DREFTYPES


class FakeXPDataRef:
    """
    FakeXP DataRef subsystem using a single global lock.

    IMPORTANT:
      • Do NOT implement __init__ in this subsystem class.
      • FakeXP composes subsystems and calls `_init_dataref()` during initialization.
      • This subsystem explicitly declares the FakeXP API endpoints it exposes.
        FakeXP must bind ONLY these names onto the xp facade.
    """

    xp: FakeXPInterface  # established by FakeXP during subsystem composition

    # ------------------------------------------------------------------
    # Public FakeXP API surface
    # ------------------------------------------------------------------
    public_api_names = [
        # Explicit registration
        "promote_handle",
        "update_dataref",

        # Lookup + metadata
        "findDataRef",
        "getDataRefInfo",
        "getDataRefTypes",
        "canWriteDataRef",
        "isDataRefGood",

        # Scalar accessors
        "getDatai", "setDatai",
        "getDataf", "setDataf",
        "getDatad", "setDatad",

        # Array accessors
        "getDatavf", "setDatavf",
        "getDatavi", "setDatavi",
        "getDatab", "setDatab",

        # String helpers
        "getDatas", "setDatas",
    ]

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def _init_dataref(self) -> None:
        """
        Initialize internal state for the DataRef subsystem.
        This method is called by FakeXP; do not call from subsystem constructors.
        """
        self._handles: Dict[str, FakeDataRef] = {}
        # accessor metadata for registered accessors (name -> metadata)
        self._accessors: Dict[str, Dict[str, Any]] = {}
        self._handle_callback: Optional[Callable[[FakeDataRef], None]] = None
        # single global lock protecting _handles and all handle state
        self._handles_lock = threading.RLock()
        # simple owner id counter for registered accessors
        self._next_owner_id = 1

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

    def _notify_handle_created(self, ref: FakeDataRef) -> None:
        # read callback under lock, but invoke it outside to avoid deadlocks
        cb = None
        with self._handles_lock:
            cb = self._handle_callback
        if cb is None:
            return
        try:
            cb(ref)
        except Exception:
            try:
                if hasattr(self.xp, "log"):
                    self.xp.log(f"[FakeXP] handle callback raised for {ref.path}")
            except Exception:
                pass

    # -------------------------
    # Defaults and helpers
    # -------------------------
    @staticmethod
    def _default_value_for(dtype: DRefType, size: int):
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
    def _dreftype_to_bitmask(dtype: DRefType, is_array: bool) -> int:
        """
        Map internal DRefType + is_array to XPLM bitmask.
        """
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

    # -------------------------
    # Lookup / dummy creation
    # -------------------------
    def findDataRef(self, name: str) -> Optional[FakeDataRef]:
        """
        Return a FakeDataRef handle. If missing, create a dummy (is_dummy=True)
        with conservative defaults, notify the runner synchronously via the
        attached callback, and return the handle immediately.

        Signature matches production: accepts a string name and returns a handle or None.
        """
        with self._handles_lock:
            existing = self._handles.get(name)
            if existing is not None:
                return existing
            # dummy default: FLOAT scalar
            dtype = DRefType.FLOAT
            size = 1
            value = self._default_value_for(dtype, size)
            ref = FakeDataRef(
                path=name,
                type=dtype,
                writable=True,
                size=size,
                value=value,
                is_dummy=True,
            )
            self._handles[name] = ref
        # notify outside global lock to avoid deadlocks in runner
        self._notify_handle_created(ref)
        return ref

    # -------------------------
    # Introspection and enumeration
    # -------------------------
    def getDataRefTypes(self, dataRef: FakeDataRef) -> int:
        """
        Return the XPLM bitmask of supported types for the provided dataRef handle.
        Signature matches production: accepts a dataRef handle only.
        """
        if not isinstance(dataRef, FakeDataRef):
            raise TypeError("invalid dataRef")
        with self._handles_lock:
            stored = self._handles.get(dataRef.path)
            if stored is None or stored is not dataRef:
                raise TypeError("invalid dataRef")
            return self._dreftype_to_bitmask(stored.type, stored.is_array)

    def getDataRefInfo(self, dataRef: FakeDataRef) -> XPLMDataRefInfo_t:
        """
        Construct and return an XPLMDataRefInfo_t instance from the FakeDataRef metadata.
        Signature matches production: accepts a dataRef handle only.
        """
        if not isinstance(dataRef, FakeDataRef):
            raise TypeError("invalid dataRef")
        with self._handles_lock:
            stored = self._handles.get(dataRef.path)
            if stored is None or stored is not dataRef:
                raise TypeError("invalid dataRef")
            bitmask = self._dreftype_to_bitmask(stored.type, stored.is_array)
            info = XPLMDataRefInfo_t(
                name=stored.path,
                type=bitmask,
                writable=bool(stored.writable),
                owner=0,
            )
            # attach derived array metadata for parity with consumers
            setattr(info, "is_array", bool(stored.is_array))
            setattr(info, "size", int(stored.size))
            return info

    def canWriteDataRef(self, dataRef: FakeDataRef) -> bool:
        """
        Return True if the dataRef is writable.
        """
        if not isinstance(dataRef, FakeDataRef):
            raise TypeError("invalid dataRef")
        with self._handles_lock:
            stored = self._handles.get(dataRef.path)
            if stored is None or stored is not dataRef:
                raise TypeError("invalid dataRef")
            return bool(stored.writable)

    def isDataRefGood(self, dataRef: FakeDataRef) -> bool:
        """
        Return True if the handle is still valid (registered and not unregistered).
        """
        if not isinstance(dataRef, FakeDataRef):
            return False
        with self._handles_lock:
            stored = self._handles.get(dataRef.path)
            return stored is dataRef

    def countDataRefs(self) -> int:
        """
        Return the total number of registered datarefs (including dummies and registered accessors).
        """
        with self._handles_lock:
            return len(self._handles)

    def getDataRefsByIndex(self, offset: int = 0, count: int = -1) -> List[FakeDataRef]:
        """
        Return a list of dataRef handles by index paging. If count == -1 return all from offset.
        """
        with self._handles_lock:
            keys = list(self._handles.keys())
            if offset < 0:
                offset = 0
            if count == -1:
                selected = keys[offset:]
            else:
                selected = keys[offset: offset + count]
            return [self._handles[k] for k in selected]

    # -------------------------
    # Registration / publishing
    # -------------------------
    def registerDataAccessor(
        self,
        name: str,
        *,
        dataType: int = 0,
        writable: int = -1,
        readInt: Optional[Callable[[Any], int]] = None,
        writeInt: Optional[Callable[[Any, int], None]] = None,
        readFloat: Optional[Callable[[Any], float]] = None,
        writeFloat: Optional[Callable[[Any, float], None]] = None,
        readDouble: Optional[Callable[[Any], float]] = None,
        writeDouble: Optional[Callable[[Any, float], None]] = None,
        readIntArray: Optional[Callable[[Any, MutableSequence[int], int, int], int]] = None,
        writeIntArray: Optional[Callable[[Any, Sequence[int], int, int], None]] = None,
        readFloatArray: Optional[Callable[[Any, MutableSequence[float], int, int], int]] = None,
        writeFloatArray: Optional[Callable[[Any, Sequence[float], int, int], None]] = None,
        readData: Optional[Callable[[Any, bytearray, int, int], int]] = None,
        writeData: Optional[Callable[[Any, Sequence[int], int, int], None]] = None,
        readRefCon: Optional[Any] = None,
        writeRefCon: Optional[Any] = None,
    ) -> FakeDataRef:
        """
        Register callbacks and return a dataref handle. Signature mirrors XPLMRegisterDataAccessor.
        If dataType == 0 or writable == -1, compute from provided callbacks.
        """
        # compute inferred bitmask if requested
        inferred_mask = Type_Unknown
        # infer scalar types
        if readInt or writeInt:
            inferred_mask |= Type_Int
        if readFloat or writeFloat:
            inferred_mask |= Type_Float
        if readDouble or writeDouble:
            inferred_mask |= Type_Double
        # infer arrays/data
        if readFloatArray or writeFloatArray:
            inferred_mask |= Type_FloatArray
        if readIntArray or writeIntArray:
            inferred_mask |= Type_IntArray
        if readData or writeData:
            inferred_mask |= Type_Data

        mask = dataType if dataType != 0 else inferred_mask
        if writable != -1:
            writable_flag = bool(writable)
        else:
            # writable if any write callback provided
            writable_flag = any((
                writeInt, writeFloat, writeDouble,
                writeIntArray, writeFloatArray, writeData
            ))

        # create or replace handle
        with self._handles_lock:
            existing = self._handles.get(name)
            if existing is not None:
                # replace metadata but keep same handle object (SDK returns a handle)
                ref = existing
                ref.type = self._bitmask_to_dreftype(mask)
                # is_array is derived from type; size preserved unless caller wants to change later
                ref.size = ref.size or 1
                ref.writable = bool(writable_flag)
                ref.is_dummy = False
            else:
                # choose a DRefType and default buffer based on mask
                dtype, _, size = self._choose_dtype_from_mask(mask)
                value = self._default_value_for(dtype, size)
                ref = FakeDataRef(
                    path=name,
                    type=dtype,
                    writable=bool(writable_flag),
                    size=size,
                    value=value,
                    is_dummy=False,
                )
                self._handles[name] = ref

            owner = self._next_owner_id
            self._next_owner_id += 1
            # store accessor metadata
            self._accessors[name] = {
                "owner": owner,
                "mask": mask,
                "writable": bool(writable_flag),
                "readInt": readInt,
                "writeInt": writeInt,
                "readFloat": readFloat,
                "writeFloat": writeFloat,
                "readDouble": readDouble,
                "writeDouble": writeDouble,
                "readIntArray": readIntArray,
                "writeIntArray": writeIntArray,
                "readFloatArray": readFloatArray,
                "writeFloatArray": writeFloatArray,
                "readData": readData,
                "writeData": writeData,
                "readRefCon": readRefCon,
                "writeRefCon": writeRefCon,
            }
        # notify outside lock
        self._notify_handle_created(ref)
        return ref

    def unregisterDataAccessor(self, dataRef: FakeDataRef) -> None:
        """
        Unregister a previously registered accessor. Subsequent calls using the handle should raise TypeError.
        """
        if not isinstance(dataRef, FakeDataRef):
            raise TypeError("invalid dataRef")
        with self._handles_lock:
            stored = self._handles.get(dataRef.path)
            if stored is None or stored is not dataRef:
                raise TypeError("invalid dataRef")
            # remove accessor metadata and handle
            self._accessors.pop(dataRef.path, None)
            # remove handle entry to mark it invalid
            del self._handles[dataRef.path]

    # -------------------------
    # Helpers for registerDataAccessor
    # -------------------------
    def _bitmask_is_array(self, mask: int) -> bool:
        return bool(mask & (Type_FloatArray | Type_IntArray | Type_Data))

    def _bitmask_to_dreftype(self, mask: int) -> DRefType:
        # prefer array types if present
        if mask & Type_FloatArray:
            return DRefType.FLOAT_ARRAY
        if mask & Type_IntArray:
            return DRefType.INT_ARRAY
        if mask & Type_Data:
            return DRefType.BYTE_ARRAY
        # scalars
        if mask & Type_Double:
            return DRefType.DOUBLE
        if mask & Type_Float:
            return DRefType.FLOAT
        if mask & Type_Int:
            return DRefType.INT
        return DRefType.FLOAT

    def _choose_dtype_from_mask(self, mask: int) -> Tuple[DRefType, bool, int]:
        """
        Choose a DRefType, is_array (returned for compatibility), and default size from a bitmask.
        Default array size is 1 for scalars, 8 for common arrays (arbitrary).
        """
        if mask & Type_FloatArray:
            return (DRefType.FLOAT_ARRAY, True, 8)
        if mask & Type_IntArray:
            return (DRefType.INT_ARRAY, True, 8)
        if mask & Type_Data:
            return (DRefType.BYTE_ARRAY, True, 256)
        if mask & Type_Double:
            return (DRefType.DOUBLE, False, 1)
        if mask & Type_Float:
            return (DRefType.FLOAT, False, 1)
        if mask & Type_Int:
            return (DRefType.INT, False, 1)
        return (DRefType.FLOAT, False, 1)

    # -------------------------
    # Internal resolver (handle-only)
    # -------------------------
    def _resolve_ref(self, dataRef: FakeDataRef) -> FakeDataRef:
        if not isinstance(dataRef, FakeDataRef):
            raise TypeError("invalid dataRef")
        with self._handles_lock:
            ref = self._handles.get(dataRef.path)
            if ref is None or ref is not dataRef:
                raise TypeError("invalid dataRef")
            return ref

    # -------------------------
    # Scalar accessors (guarded by global lock)
    # -------------------------
    def getDatai(self, dataRef: FakeDataRef) -> int:
        ref = self._resolve_ref(dataRef)
        cb = None
        refcon = None
        with self._handles_lock:
            meta = self._accessors.get(ref.path)
            if meta:
                cb = meta.get("readInt")
                refcon = meta.get("readRefCon")
            if cb is None:
                return int(ref.value)
        return int(cb(refcon))

    def setDatai(self, dataRef: FakeDataRef, v: int) -> None:
        ref = self._resolve_ref(dataRef)
        cb = None
        refcon = None
        with self._handles_lock:
            if not ref.writable:
                raise PermissionError("DataRef not writable")
            meta = self._accessors.get(ref.path)
            if meta:
                cb = meta.get("writeInt")
                refcon = meta.get("writeRefCon")
            if cb is None:
                ref.value = int(v)
                return
        cb(refcon, int(v))

    def getDataf(self, dataRef: FakeDataRef) -> float:
        ref = self._resolve_ref(dataRef)
        cb = None
        refcon = None
        with self._handles_lock:
            meta = self._accessors.get(ref.path)
            if meta:
                cb = meta.get("readFloat") or meta.get("readDouble")
                refcon = meta.get("readRefCon")
            if cb is None:
                return float(ref.value)
        return float(cb(refcon))

    def setDataf(self, dataRef: FakeDataRef, v: float) -> None:
        ref = self._resolve_ref(dataRef)
        cb = None
        refcon = None
        with self._handles_lock:
            if not ref.writable:
                raise PermissionError("DataRef not writable")
            meta = self._accessors.get(ref.path)
            if meta:
                cb = meta.get("writeFloat") or meta.get("writeDouble")
                refcon = meta.get("writeRefCon")
            if cb is None:
                ref.value = float(v)
                return
        cb(refcon, float(v))

    def getDatad(self, dataRef: FakeDataRef) -> float:
        return self.getDataf(dataRef)

    def setDatad(self, dataRef: FakeDataRef, v: float) -> None:
        return self.setDataf(dataRef, v)

    # -------------------------
    # Array accessors (guarded by global lock)
    # -------------------------

    def _array_get_common(
        self,
        *,
        ref: FakeDataRef,
        values: Optional[MutableSequence[Any]],
        offset: int,
        count: int,
        read_cb: Optional[Callable[[Any, MutableSequence[Any], int, int], int]],
        refcon: Any,
    ) -> int:
        """
        Shared helper for array getters.

        Semantics:
          • offset is SOURCE offset into the dataref array (XPLM semantics)
          • Destination placement:
              - if len(values) == count → write to values[0:count]
              - if len(values) > count → write to values[offset:offset+count]
          • Callbacks always write to a temporary buffer, then we copy.
        """
        arr = ref.value

        if values is None or count < 0:
            return len(arr)

        if offset < 0:
            offset = 0

        dest_start = 0 if len(values) == count else offset
        if dest_start + count > len(values):
            raise RuntimeError("array buffer too small for provided offset+count")

        # Callback path
        if read_cb is not None:
            tmp = [0] * count
            got = int(read_cb(refcon, tmp, offset, count))
            for i in range(got):
                values[dest_start + i] = tmp[i]
            return got

        # Direct storage path
        if offset + count > len(arr):
            raise RuntimeError("array read would go past end of dataRef")

        for i in range(count):
            values[dest_start + i] = arr[offset + i]
        return count

    def getDatavf(
        self,
        dataRef: FakeDataRef,
        values: Optional[MutableSequence[float]] = None,
        offset: int = 0,
        count: int = -1,
    ) -> int:
        ref = self._resolve_ref(dataRef)
        with self._handles_lock:
            if ref.type != DRefType.FLOAT_ARRAY:
                raise TypeError("getDatavf called on non-float-array")

            meta = self._accessors.get(ref.path)
            read_cb = meta.get("readFloatArray") if meta else None
            refcon = meta.get("readRefCon") if meta else None

            return self._array_get_common(
                ref=ref,
                values=values,
                offset=offset,
                count=count,
                read_cb=read_cb,
                refcon=refcon,
            )

    def getDatavi(
        self,
        dataRef: FakeDataRef,
        values: Optional[MutableSequence[int]] = None,
        offset: int = 0,
        count: int = -1,
    ) -> int:
        ref = self._resolve_ref(dataRef)
        with self._handles_lock:
            if ref.type != DRefType.INT_ARRAY:
                raise TypeError("getDatavi called on non-int-array")

            meta = self._accessors.get(ref.path)
            read_cb = meta.get("readIntArray") if meta else None
            refcon = meta.get("readRefCon") if meta else None

            return self._array_get_common(
                ref=ref,
                values=values,
                offset=offset,
                count=count,
                read_cb=read_cb,
                refcon=refcon,
            )

    def getDatab(
        self,
        dataRef: FakeDataRef,
        values: Optional[bytearray] = None,
        offset: int = 0,
        count: int = -1,
    ) -> int:
        ref = self._resolve_ref(dataRef)
        with self._handles_lock:
            if ref.type != DRefType.BYTE_ARRAY:
                raise TypeError("getDatab called on non-byte-array")

            meta = self._accessors.get(ref.path)
            read_cb = meta.get("readData") if meta else None
            refcon = meta.get("readRefCon") if meta else None

            return self._array_get_common(
                ref=ref,
                values=values,
                offset=offset,
                count=count,
                read_cb=read_cb,
                refcon=refcon,
            )

    def setDatavf(
        self,
        dataRef: FakeDataRef,
        values: Sequence[float],
        offset: int = 0,
        count: int = -1,
    ) -> int:
        ref = self._resolve_ref(dataRef)
        with self._handles_lock:
            if not ref.writable:
                raise PermissionError("DataRef not writable")
            if ref.type != DRefType.FLOAT_ARRAY:
                raise TypeError("setDatavf called on non-float-array")

            if count < 0:
                count = len(values)
            if count > len(values):
                raise RuntimeError("setDatavf list too short for provided count")
            if offset < 0:
                offset = 0

            meta = self._accessors.get(ref.path)
            write_cb = meta.get("writeFloatArray") if meta else None
            refcon = meta.get("writeRefCon") if meta else None

            # Dummy: replace backing buffer
            if ref.is_dummy and write_cb is None:
                new_size = offset + count
                buf = [0.0] * new_size
                for i in range(count):
                    buf[offset + i] = float(values[i])
                ref.value = buf
                ref.size = new_size
                return count

            # Real: in-place, bounds enforced
            if not ref.is_dummy:
                if offset + count > len(ref.value):
                    raise RuntimeError("setDatavf would write past end of dataRef")

            if write_cb is None:
                for i in range(count):
                    ref.value[offset + i] = float(values[i])
                return count

        write_cb(refcon, values, offset, count)
        return count

    def setDatavi(
        self,
        dataRef: FakeDataRef,
        values: Sequence[int],
        offset: int = 0,
        count: int = -1,
    ) -> int:
        ref = self._resolve_ref(dataRef)
        with self._handles_lock:
            if not ref.writable:
                raise PermissionError("DataRef not writable")
            if ref.type != DRefType.INT_ARRAY:
                raise TypeError("setDatavi called on non-int-array")

            if count < 0:
                count = len(values)
            if count > len(values):
                raise RuntimeError("setDatavi list too short for provided count")
            if offset < 0:
                offset = 0

            meta = self._accessors.get(ref.path)
            write_cb = meta.get("writeIntArray") if meta else None
            refcon = meta.get("writeRefCon") if meta else None

            if ref.is_dummy and write_cb is None:
                new_size = offset + count
                buf = [0] * new_size
                for i in range(count):
                    buf[offset + i] = int(values[i])
                ref.value = buf
                ref.size = new_size
                return count

            if not ref.is_dummy:
                if offset + count > len(ref.value):
                    raise RuntimeError("setDatavi would write past end of dataRef")

            if write_cb is None:
                for i in range(count):
                    ref.value[offset + i] = int(values[i])
                return count

        write_cb(refcon, values, offset, count)
        return count

    def setDatab(
        self,
        dataRef: FakeDataRef,
        values: Sequence[int],
        offset: int = 0,
        count: int = -1,
    ) -> int:
        ref = self._resolve_ref(dataRef)
        with self._handles_lock:
            if not ref.writable:
                raise PermissionError("DataRef not writable")
            if ref.type != DRefType.BYTE_ARRAY:
                raise TypeError("setDatab called on non-byte-array")

            if count < 0:
                count = len(values)
            if count > len(values):
                raise RuntimeError("setDatab list too short for provided count")
            if offset < 0:
                offset = 0

            meta = self._accessors.get(ref.path)
            write_cb = meta.get("writeData") if meta else None
            refcon = meta.get("writeRefCon") if meta else None

            if ref.is_dummy and write_cb is None:
                new_size = offset + count
                buf = bytearray(new_size)
                for i in range(count):
                    buf[offset + i] = int(values[i]) & 0xFF
                ref.value = buf
                ref.size = new_size
                return count

            if not ref.is_dummy:
                if offset + count > len(ref.value):
                    raise RuntimeError("setDatab would write past end of dataRef")

            if write_cb is None:
                for i in range(count):
                    ref.value[offset + i] = int(values[i]) & 0xFF
                return count

        write_cb(refcon, values, offset, count)
        return count

    # -------------------------
    # String helpers (XPPython3 convenience)
    # -------------------------
    def getDatas(self, dataRef: FakeDataRef, offset: int = 0, count: int = -1) -> str:
        """
        Return decoded UTF-8 string up to first null byte or up to count.
        """
        ref = self._resolve_ref(dataRef)
        with self._handles_lock:
            if ref.type != DRefType.BYTE_ARRAY:
                raise TypeError("getDatas called on non-byte-array")
            arr: bytearray = ref.value
            if count < 0:
                count = len(arr) - offset
            raw = bytes(arr[offset: offset + count])
        raw = raw.split(b"\x00", 1)[0]
        return raw.decode("utf-8", errors="ignore")

    def setDatas(self, dataRef: FakeDataRef, value: str, offset: int = 0, count: int = -1) -> None:
        """
        Write string into byte-array dataref with padding/truncation semantics.
        """
        ref = self._resolve_ref(dataRef)
        with self._handles_lock:
            if not ref.writable:
                raise PermissionError("DataRef not writable")
            if ref.type != DRefType.BYTE_ARRAY:
                raise TypeError("setDatas called on non-byte-array")
            arr: bytearray = ref.value
            b = value.encode("utf-8")
            if count < 0:
                count = len(b)
            if offset + count > len(arr):
                raise RuntimeError("setDatas would write past end of dataRef")
            for i in range(count):
                arr[offset + i] = b[i] if i < len(b) else 0

    # -------------------------
    # Dummy update and promotion helpers
    # -------------------------

    def promote_handle(
        self,
        ref: FakeDataRef,
        dtype: DRefType,
        is_array: bool,
        size: int,
        writable: bool,
        default_value: Optional[Any] = None,
        preserve_dummy_writes: bool = True,
    ) -> None:
        """
        Promote an existing handle in-place (dummy -> real) and update metadata.

        Semantics:
          • Promotion is in-place: the same FakeDataRef object is updated.
          • If preserve_dummy_writes is True, keep existing value when compatible.
          • If preserve_dummy_writes is False, replace with default_value or dtype default.
          • Size is authoritative for real handles; arrays are resized to `size`.

        Raises:
          • ValueError on invalid size
          • TypeError if ref is invalid
        """
        if size <= 0:
            raise ValueError("size must be > 0")

        with self._handles_lock:
            if ref is None:
                raise TypeError("invalid dataRef")

            # Update metadata first
            ref.type = dtype
            ref.writable = bool(writable)
            ref.size = int(size)

            # Decide new value
            if not preserve_dummy_writes:
                if default_value is not None:
                    ref.value = copy.deepcopy(default_value)
                else:
                    ref.value = self._default_value_for(dtype, ref.size)
                ref.is_dummy = False
                return

            # preserve_dummy_writes=True
            if is_array:
                # If previous value was scalar, cannot preserve into array safely
                if not isinstance(ref.value, (list, bytearray)):
                    ref.value = self._default_value_for(dtype, ref.size)
                else:
                    if dtype == DRefType.BYTE_ARRAY:
                        buf = bytearray(ref.value)
                        if len(buf) < ref.size:
                            buf.extend(b"\x00" * (ref.size - len(buf)))
                        else:
                            buf = buf[: ref.size]
                        ref.value = buf
                    elif dtype == DRefType.FLOAT_ARRAY:
                        buf = [float(x) for x in list(ref.value)]
                        if len(buf) < ref.size:
                            buf.extend([0.0] * (ref.size - len(buf)))
                        else:
                            buf = buf[: ref.size]
                        ref.value = buf
                    elif dtype == DRefType.INT_ARRAY:
                        buf = [int(x) for x in list(ref.value)]
                        if len(buf) < ref.size:
                            buf.extend([0] * (ref.size - len(buf)))
                        else:
                            buf = buf[: ref.size]
                        ref.value = buf
                    else:
                        ref.value = self._default_value_for(dtype, ref.size)
            else:
                # Scalar promotion
                if isinstance(ref.value, (list, bytearray)):
                    ref.value = self._default_value_for(dtype, 1)
                else:
                    if dtype in (DRefType.FLOAT, DRefType.DOUBLE):
                        ref.value = float(ref.value)
                    elif dtype == DRefType.INT:
                        ref.value = int(ref.value)
                    else:
                        ref.value = self._default_value_for(dtype, 1)
                ref.size = 1

            ref.is_dummy = False

    # -------------------------
    # DataRef update helper
    # -------------------------
    def update_dataref(
        self,
        ref: FakeDataRef,
        dtype: Optional[DRefType] = None,
        size: Optional[int] = None,
        writable: Optional[bool] = None,
        value: Optional[Any] = None,
    ) -> FakeDataRef:
        """
        Update an existing FakeDataRef in-place (dummy or live).

        Semantics:
          • Handle identity is preserved.
          • is_dummy is NOT modified.
          • dtype/size/writable updated if provided.
          • Arrays replace the backing buffer atomically.
          • Scalars are coerced.
          • No promotion logic is applied.

        Raises:
          • ValueError on invalid size
          • TypeError if ref is invalid
        """
        with self._handles_lock:
            if ref is None:
                raise TypeError("invalid dataRef")

            if size is not None:
                if size <= 0:
                    raise ValueError("size must be > 0")
                ref.size = int(size)

            if dtype is not None:
                ref.type = dtype

            if writable is not None:
                ref.writable = bool(writable)

            if value is None:
                return ref

            # Array types: replace backing buffer
            if ref.type == DRefType.FLOAT_ARRAY:
                buf = [float(x) for x in value]
                buf = (buf + [0.0] * ref.size)[: ref.size]
                ref.value = buf
                return ref

            if ref.type == DRefType.INT_ARRAY:
                buf = [int(x) for x in value]
                buf = (buf + [0] * ref.size)[: ref.size]
                ref.value = buf
                return ref

            if ref.type == DRefType.BYTE_ARRAY:
                buf = bytearray(value)
                buf = (buf + b"\x00" * ref.size)[: ref.size]
                ref.value = buf
                return ref

            # Scalar types
            ref.size = 1
            if ref.type in (DRefType.FLOAT, DRefType.DOUBLE):
                ref.value = float(value)
            elif ref.type == DRefType.INT:
                ref.value = int(value)
            else:
                ref.value = copy.deepcopy(value)

            return ref
