# simless/libs/fake_xp_dataref_api.py
# =======================================================================
# FakeXP DataRef public API implementation
#
# This module implements the full xp.* DataRef surface with production‑
# parity semantics. It assumes that the composing class provides:
#
#   • self._handles: Dict[str, FakeDataRef]
#   • self._accessors: Dict[str, Dict[str, Any]]
#   • self._handles_lock: threading.RLock
#
# In addition, this API expects the composing FakeXPDataRef to expose
# explicit promotion methods:
#
#   • self.promote_type(ref: FakeDataRef, dtype: DRefType, writable: bool) -> None
#   • self.promote_shape_from_value(ref: FakeDataRef, value: Any) -> None
#
# Lifecycle, bridge integration, and environment wiring are owned by the
# composing FakeXPDataRef class.
# =======================================================================

from __future__ import annotations

from threading import RLock
from typing import Any, Callable, Dict, List, MutableSequence, Optional, Sequence, Tuple

from simless.libs.fake_xp_types import (
    FakeDataRef, Type_Data, Type_Double, Type_Float, Type_FloatArray, Type_Int, Type_IntArray, Type_Unknown
)
from simless.libs.fake_xp_interface import FakeXPInterface
from sshd_extensions.dataref_manager import DRefType
from XPPython3.xp_typing import XPLMDataRefInfo_t


class FakeXPDataRefAPI:
    """
    Public xp.* DataRef API implementation.

    This class implements all DataRef behavior visible to plugins.
    It does not own lifecycle or bridge wiring.
    """

    xp: FakeXPInterface  # established by FakeXP during subsystem composition
    _handle_callback: Optional[Callable[[FakeDataRef], None]]
    _handles: Dict[str, FakeDataRef]
    # accessor metadata for registered accessors (name -> metadata)
    _accessors: Dict[str, Dict[str, Any]]
    # single global lock protecting _handles and all handle state
    _handles_lock: RLock
    # simple owner id counter for registered accessors
    _next_owner_id: int

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
    def _dreftype_to_bitmask(dtype: DRefType, is_array: Optional[bool]) -> int:
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

    def _require_array(self, ref: FakeDataRef, api: str) -> None:
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

    def _require_scalar(self, ref: FakeDataRef, api: str) -> None:
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

    # ------------------------------------------------------------------
    # Lookup / dummy creation
    # ------------------------------------------------------------------
    def findDataRef(self, name: str) -> Optional[FakeDataRef]:
        existing = self.xp.get_handle(name)
        if existing is not None:
            return existing

        ref = FakeDataRef(
            path=name,
            type=DRefType.FLOAT,
            writable=True,
            size=1,
            value=0.0,
        )
        self.xp.add_handle(name, ref)

        self._notify_handle_created(ref)
        return ref

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def getDataRefTypes(self, dataRef: FakeDataRef) -> int:
        ref = self._resolve_ref(dataRef)
        is_array = ref.is_array if getattr(ref, "shape_known", False) else None
        return self._dreftype_to_bitmask(ref.type, is_array)

    def getDataRefInfo(self, dataRef: FakeDataRef) -> XPLMDataRefInfo_t:
        ref = self._resolve_ref(dataRef)
        is_array = ref.is_array if getattr(ref, "shape_known", False) else None
        info = XPLMDataRefInfo_t(
            name=ref.path,
            type=self._dreftype_to_bitmask(ref.type, is_array),
            writable=bool(ref.writable),
            owner=0,
        )
        setattr(info, "is_array", is_array)
        setattr(info, "size", ref.size if getattr(ref, "shape_known", False) else 0)
        return info

    def canWriteDataRef(self, dataRef: FakeDataRef) -> bool:
        return self._resolve_ref(dataRef).writable

    def isDataRefGood(self, dataRef: FakeDataRef) -> bool:
        try:
            self._resolve_ref(dataRef)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal resolver
    # ------------------------------------------------------------------
    def _resolve_ref(self, dataRef: FakeDataRef) -> FakeDataRef:
        if not isinstance(dataRef, FakeDataRef):
            raise TypeError("invalid dataRef")
        ref = self.xp.get_handle(dataRef.path)
        if ref is None or ref is not dataRef:
            raise TypeError("invalid dataRef")
        return ref

    # ------------------------------------------------------------------
    # Scalar accessors
    # ------------------------------------------------------------------
    def getDatai(self, dataRef: FakeDataRef) -> int:
        ref = self._resolve_ref(dataRef)
        self._require_scalar(ref, "getDatai")
        meta = self._accessors.get(ref.path)
        if meta and meta.get("readInt"):
            return int(meta["readInt"](meta.get("readRefCon")))
        return int(ref.value)

    def getDataf(self, dataRef: FakeDataRef) -> float:
        ref = self._resolve_ref(dataRef)
        self._require_scalar(ref, "getDataf")
        meta = self._accessors.get(ref.path)
        cb = meta.get("readFloat") or meta.get("readDouble") if meta else None
        if cb:
            return float(cb(meta.get("readRefCon")))
        return float(ref.value)

    def getDatad(self, dataRef: FakeDataRef) -> float:
        return self.getDataf(dataRef)

    def setDataf(self, dataRef: FakeDataRef, v: float) -> None:
        ref = self._resolve_ref(dataRef)

        # Dummy has no contract — conform before enforcing
        if ref.is_dummy:
            self.xp.conform_dummy_to_value(ref, float(v))

        # Now enforce scalar contract
        self._require_scalar(ref, "setDataf")

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        meta = self._accessors.get(ref.path)
        cb = (meta.get("writeFloat") or meta.get("writeDouble")) if meta else None

        if cb:
            cb(meta.get("writeRefCon"), float(v))
        else:
            ref.value = float(v)

    def setDatai(self, dataRef: FakeDataRef, v: int) -> None:
        ref = self._resolve_ref(dataRef)

        # Dummy has no contract — conform first
        if ref.is_dummy:
            self.xp.conform_dummy_to_value(ref, int(v))

        # Enforce scalar contract
        self._require_scalar(ref, "setDatai")

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        meta = self._accessors.get(ref.path)
        cb = meta.get("writeInt") if meta else None

        if cb:
            cb(meta.get("writeRefCon"), int(v))
        else:
            ref.value = int(v)

    def setDatad(self, dataRef: FakeDataRef, v: float) -> None:
        ref = self._resolve_ref(dataRef)

        # Dummy has no contract — conform first
        if ref.is_dummy:
            self.xp.conform_dummy_to_value(ref, float(v))

        # Enforce scalar contract
        self._require_scalar(ref, "setDatad")

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        meta = self._accessors.get(ref.path)
        cb = meta.get("writeDouble") if meta else None

        if cb:
            cb(meta.get("writeRefCon"), float(v))
        else:
            ref.value = float(v)

    # ------------------------------------------------------------------
    # Array helpers
    # ------------------------------------------------------------------
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
        self._require_array(ref, "_array_get_common")
        arr = ref.value

        if values is None or count < 0:
            return len(arr)

        if offset < 0:
            offset = 0

        dest_start = 0 if len(values) == count else offset
        if dest_start + count > len(values):
            raise RuntimeError("array buffer too small")

        if read_cb:
            tmp = [0] * count
            got = int(read_cb(refcon, tmp, offset, count))
            for i in range(got):
                values[dest_start + i] = tmp[i]
            return got

        if offset + count > len(arr):
            raise RuntimeError("array read past end")

        for i in range(count):
            values[dest_start + i] = arr[offset + i]
        return count

    # ------------------------------------------------------------------
    # Array accessors
    # ------------------------------------------------------------------
    def getDatavf(self, dataRef, values=None, offset=0, count=-1) -> int:
        ref = self._resolve_ref(dataRef)
        if ref.type != DRefType.FLOAT_ARRAY:
            raise TypeError("getDatavf on non-float-array")
        meta = self._accessors.get(ref.path)
        return self._array_get_common(
            ref=ref,
            values=values,
            offset=offset,
            count=count,
            read_cb=meta.get("readFloatArray") if meta else None,
            refcon=meta.get("readRefCon") if meta else None,
        )

    def getDatavi(self, dataRef, values=None, offset=0, count=-1) -> int:
        ref = self._resolve_ref(dataRef)
        if ref.type != DRefType.INT_ARRAY:
            raise TypeError("getDatavi on non-int-array")
        meta = self._accessors.get(ref.path)
        return self._array_get_common(
            ref=ref,
            values=values,
            offset=offset,
            count=count,
            read_cb=meta.get("readIntArray") if meta else None,
            refcon=meta.get("readRefCon") if meta else None,
        )

    def getDatab(self, dataRef, values=None, offset=0, count=-1) -> int:
        ref = self._resolve_ref(dataRef)
        if ref.type != DRefType.BYTE_ARRAY:
            raise TypeError("getDatab on non-byte-array")
        meta = self._accessors.get(ref.path)
        return self._array_get_common(
            ref=ref,
            values=values,
            offset=offset,
            count=count,
            read_cb=meta.get("readData") if meta else None,
            refcon=meta.get("readRefCon") if meta else None,
        )

    def setDatavf(self, dataRef, values, offset=0, count=-1) -> int:
        ref = self._resolve_ref(dataRef)
        if not ref.writable:
            raise PermissionError("DataRef not writable")

        # Dummy has no contract — conform first
        if ref.is_dummy:
            self.xp.conform_dummy_to_value(ref, values, offset, count)

        if ref.type != DRefType.FLOAT_ARRAY:
            raise TypeError("setDatavf on non-float-array")

        if count < 0:
            count = len(values)
        if count > len(values):
            raise RuntimeError("setDatavf list too short for provided count")
        if offset < 0:
            offset = 0

        meta = self._accessors.get(ref.path)
        write_cb = meta.get("writeFloatArray") if meta else None
        refcon = meta.get("writeRefCon") if meta else None

        self._require_array(ref, "setDatavf")
        if offset + count > len(ref.value):
            raise RuntimeError("setDatavf would write past end of dataRef")

        if write_cb is None:
            for i in range(count):
                ref.value[offset + i] = float(values[i])
            return count

        write_cb(refcon, values, offset, count)
        return count

    def setDatavi(self, dataRef, values, offset=0, count=-1) -> int:
        ref = self._resolve_ref(dataRef)
        if not ref.writable:
            raise PermissionError("DataRef not writable")

        if ref.is_dummy:
            self.xp.conform_dummy_to_value(ref, values, offset, count)

        if ref.type != DRefType.INT_ARRAY:
            raise TypeError("setDatavi on non-int-array")

        if count < 0:
            count = len(values)
        if count > len(values):
            raise RuntimeError("setDatavi list too short for provided count")
        if offset < 0:
            offset = 0

        meta = self._accessors.get(ref.path)
        write_cb = meta.get("writeIntArray") if meta else None
        refcon = meta.get("writeRefCon") if meta else None

        self._require_array(ref, "setDatavi")
        if offset + count > len(ref.value):
            raise RuntimeError("setDatavi would write past end of dataRef")

        if write_cb is None:
            for i in range(count):
                ref.value[offset + i] = int(values[i])
            return count

        write_cb(refcon, values, offset, count)
        return count

    def setDatab(self, dataRef, values, offset=0, count=-1) -> int:
        ref = self._resolve_ref(dataRef)
        if not ref.writable:
            raise PermissionError("DataRef not writable")

        if ref.is_dummy:
            self.xp.conform_dummy_to_value(ref, values, offset, count)

        if ref.type != DRefType.BYTE_ARRAY:
            raise TypeError("setDatab on non-byte-array")

        if count < 0:
            count = len(values)
        if count > len(values):
            raise RuntimeError("setDatab list too short for provided count")
        if offset < 0:
            offset = 0

        meta = self._accessors.get(ref.path)
        write_cb = meta.get("writeData") if meta else None
        refcon = meta.get("writeRefCon") if meta else None

        self._require_array(ref, "setDatab")
        if offset + count > len(ref.value):
            raise RuntimeError("setDatab would write past end of dataRef")

        if write_cb is None:
            for i in range(count):
                ref.value[offset + i] = int(values[i]) & 0xFF
            return count

        write_cb(refcon, values, offset, count)
        return count

    # ------------------------------------------------------------------
    # String helpers
    # ------------------------------------------------------------------
    def getDatas(self, dataRef, offset=0, count=-1) -> str:
        ref = self._resolve_ref(dataRef)
        if ref.type != DRefType.BYTE_ARRAY:
            raise TypeError("getDatas on non-byte-array")
        self._require_array(ref, "getDatas")
        arr = ref.value
        if count < 0:
            count = len(arr) - offset
        raw = bytes(arr[offset: offset + count]).split(b"\x00", 1)[0]
        return raw.decode("utf-8", errors="ignore")

    def setDatas(self, dataRef, value: str, offset=0, count=-1) -> None:
        ref = self._resolve_ref(dataRef)
        if not ref.writable:
            raise PermissionError("DataRef not writable")
        if ref.type != DRefType.BYTE_ARRAY:
            raise TypeError("setDatas on non-byte-array")
        self._require_array(ref, "setDatas")
        arr = ref.value
        b = value.encode("utf-8")
        if count < 0:
            count = len(b)
        if offset + count > len(arr):
            raise RuntimeError("write past end")
        for i in range(count):
            arr[offset + i] = b[i] if i < len(b) else 0

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
        inferred_mask = Type_Unknown
        if readInt or writeInt:
            inferred_mask |= Type_Int
        if readFloat or writeFloat:
            inferred_mask |= Type_Float
        if readDouble or writeDouble:
            inferred_mask |= Type_Double
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
            writable_flag = any(
                (
                    writeInt, writeFloat, writeDouble,
                    writeIntArray, writeFloatArray, writeData
                )
            )

        dtype, is_array, size = self._choose_dtype_from_mask(mask)
        default_value = self._default_value_for(dtype, size)

        existing = self.xp.get_handle(name)
        if existing is not None:
            ref = existing
        else:
            ref = FakeDataRef(
                path=name,
                type=dtype,
                writable=bool(writable_flag),
                size=1,
                value=0.0,
            )
            self.xp.add_handle(name, ref)

            # Explicit promotions: registration is authoritative.
            self.xp.promote_type(ref=ref, dtype=dtype, writable=bool(writable_flag))
            self.xp.promote_shape_from_value(ref=ref, value=default_value)

            owner = self._next_owner_id
            self._next_owner_id += 1
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

        self._notify_handle_created(ref)
        return ref

    def unregisterDataAccessor(self, dataRef: FakeDataRef) -> None:
        """
        Unregister a previously registered accessor. Subsequent calls using the handle should raise TypeError.
        """
        if not isinstance(dataRef, FakeDataRef):
            raise TypeError("invalid dataRef")
        stored = self.xp.get_handle(dataRef.path)
        if stored is None or stored is not dataRef:
            raise TypeError("invalid dataRef")
        self._accessors.pop(dataRef.path, None)
        self.xp.del_handle(dataRef.path)

    # -------------------------
    # Helpers for registerDataAccessor
    # -------------------------
    def _bitmask_is_array(self, mask: int) -> bool:
        return bool(mask & (Type_FloatArray | Type_IntArray | Type_Data))

    def _bitmask_to_dreftype(self, mask: int) -> DRefType:
        if mask & Type_FloatArray:
            return DRefType.FLOAT_ARRAY
        if mask & Type_IntArray:
            return DRefType.INT_ARRAY
        if mask & Type_Data:
            return DRefType.BYTE_ARRAY
        if mask & Type_Double:
            return DRefType.DOUBLE
        if mask & Type_Float:
            return DRefType.FLOAT
        if mask & Type_Int:
            return DRefType.INT
        return DRefType.FLOAT

    def _choose_dtype_from_mask(self, mask: int) -> Tuple[DRefType, bool, int]:
        """
        Choose a DRefType, is_array, and default size from a bitmask.
        Default array size is 1 for scalars, 8 for common arrays (arbitrary).
        """
        if mask & Type_FloatArray:
            return DRefType.FLOAT_ARRAY, True, 8
        if mask & Type_IntArray:
            return DRefType.INT_ARRAY, True, 8
        if mask & Type_Data:
            return DRefType.BYTE_ARRAY, True, 256
        if mask & Type_Double:
            return DRefType.DOUBLE, False, 1
        if mask & Type_Float:
            return DRefType.FLOAT, False, 1
        if mask & Type_Int:
            return DRefType.INT, False, 1
        return DRefType.FLOAT, False, 1
