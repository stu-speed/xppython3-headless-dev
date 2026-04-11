# simless/libs/dm_dataref.py
# =======================================================================
# FakeXP DataRef public API implementation
#
# This module implements the full xp.* DataRef surface with production‑
# parity semantics. It assumes that the composing class provides:
#
#   • self.dm._handles: Dict[str, FakeDataRef]
#   • self.dm._accessors: Dict[str, Dict[str, Any]]
#   • self.dm._handles_lock: threading.RLock
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

from typing import Any, Callable, cast, List, MutableSequence, Optional, Sequence, Tuple, TYPE_CHECKING

from simless.libs.dataref import DataRefManager
from simless.libs.fake_xp_types import FakeDataRef
from XPPython3.xp_typing import XPLMDataRefInfo_t

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPDataRef:
    """
    Public xp.* DataRef API implementation.

    This class implements all DataRef behavior visible to plugins.
    It does not own lifecycle or bridge wiring.
    """

    @property
    def fake_xp(self) -> FakeXP:
        return cast("FakeXP", cast(object, self))

    @property
    def dm(self) -> DataRefManager:
        return self.fake_xp.dataref_manager

    # ------------------------------------------------------------------
    # Lookup / dummy creation
    # ------------------------------------------------------------------
    def findDataRef(self, name: str) -> Optional[FakeDataRef]:
        existing = self.dm.get_handle(name)
        if existing is not None:
            return existing

        # Dummy refs use FLOAT scalar as provisional type
        ref = FakeDataRef(
            path=name,
            type=self.fake_xp.Type_Float,
            writable=True,
            size=1,
            value=0.0,
        )
        self.dm.add_handle(name, ref)
        self.dm.notify_handle_created(ref)
        return ref

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def getDataRefTypes(self, dataRef: FakeDataRef) -> int:
        ref = self._resolve_ref(dataRef)
        is_array = ref.is_array if getattr(ref, "shape_known", False) else None
        return self.dm.dtype_to_bitmask(ref.type, is_array)

    def getDataRefInfo(self, dataRef: FakeDataRef) -> XPLMDataRefInfo_t:
        ref = self._resolve_ref(dataRef)
        is_array = ref.is_array if getattr(ref, "shape_known", False) else None
        info = XPLMDataRefInfo_t(
            name=ref.path,
            type=self.dm.dtype_to_bitmask(ref.type, is_array),
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
        ref = self.dm.get_handle(dataRef.path)
        if ref is None or ref is not dataRef:
            raise TypeError("invalid dataRef")
        return ref

    # ------------------------------------------------------------------
    # Scalar accessors
    # ------------------------------------------------------------------
    def getDatai(self, dataRef: FakeDataRef) -> int:
        ref = self._resolve_ref(dataRef)
        self.dm.require_scalar(ref, "getDatai")
        meta = self.dm._accessors.get(ref.path)
        if meta and meta.get("readInt"):
            return int(meta["readInt"](meta.get("readRefCon")))
        return int(ref.value)

    def getDataf(self, dataRef: FakeDataRef) -> float:
        ref = self._resolve_ref(dataRef)
        self.dm.require_scalar(ref, "getDataf")
        meta = self.dm._accessors.get(ref.path)
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
            self.dm.conform_dummy_to_value(ref, float(v))

        # Now enforce scalar contract
        self.dm.require_scalar(ref, "setDataf")

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        meta = self.dm._accessors.get(ref.path)
        cb = (meta.get("writeFloat") or meta.get("writeDouble")) if meta else None

        if cb:
            cb(meta.get("writeRefCon"), float(v))
        else:
            ref.value = float(v)

    def setDatai(self, dataRef: FakeDataRef, v: int) -> None:
        ref = self._resolve_ref(dataRef)

        # Dummy has no contract — conform first
        if ref.is_dummy:
            self.dm.conform_dummy_to_value(ref, int(v))

        # Enforce scalar contract
        self.dm.require_scalar(ref, "setDatai")

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        meta = self.dm._accessors.get(ref.path)
        cb = meta.get("writeInt") if meta else None

        if cb:
            cb(meta.get("writeRefCon"), int(v))
        else:
            ref.value = int(v)

    def setDatad(self, dataRef: FakeDataRef, v: float) -> None:
        ref = self._resolve_ref(dataRef)

        # Dummy has no contract — conform first
        if ref.is_dummy:
            self.dm.conform_dummy_to_value(ref, float(v))

        # Enforce scalar contract
        self.dm.require_scalar(ref, "setDatad")

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        meta = self.dm._accessors.get(ref.path)
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
        self.dm.require_array(ref, "_array_get_common")
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
        if ref.type != self.fake_xp.Type_FloatArray:
            raise TypeError("getDatavf on non-float-array")
        meta = self.dm._accessors.get(ref.path)
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
        if ref.type != self.fake_xp.Type_IntArray:
            raise TypeError("getDatavi on non-int-array")
        meta = self.dm._accessors.get(ref.path)
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
        if ref.type != self.fake_xp.Type_Data:
            raise TypeError("getDatab on non-byte-array")
        meta = self.dm._accessors.get(ref.path)
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
        fxp = self.fake_xp

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        # Dummy has no contract — conform first
        if ref.is_dummy:
            self.dm.conform_dummy_to_value(ref, values, offset, count)

        if ref.type != fxp.Type_FloatArray:
            raise TypeError("setDatavf on non-float-array")

        if count < 0:
            count = len(values)
        if count > len(values):
            raise RuntimeError("setDatavf list too short for provided count")
        if offset < 0:
            offset = 0

        meta = self.dm._accessors.get(ref.path)
        write_cb = meta.get("writeFloatArray") if meta else None
        refcon = meta.get("writeRefCon") if meta else None

        self.dm.require_array(ref, "setDatavf")
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
        fxp = self.fake_xp

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        if ref.is_dummy:
            self.dm.conform_dummy_to_value(ref, values, offset, count)

        if ref.type != fxp.Type_IntArray:
            raise TypeError("setDatavi on non-int-array")

        if count < 0:
            count = len(values)
        if count > len(values):
            raise RuntimeError("setDatavi list too short for provided count")
        if offset < 0:
            offset = 0

        meta = self.dm._accessors.get(ref.path)
        write_cb = meta.get("writeIntArray") if meta else None
        refcon = meta.get("writeRefCon") if meta else None

        self.dm.require_array(ref, "setDatavi")
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
        fxp = self.fake_xp

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        if ref.is_dummy:
            self.dm.conform_dummy_to_value(ref, values, offset, count)

        if ref.type != fxp.Type_Data:
            raise TypeError("setDatab on non-byte-array")

        if count < 0:
            count = len(values)
        if count > len(values):
            raise RuntimeError("setDatab list too short for provided count")
        if offset < 0:
            offset = 0

        meta = self.dm._accessors.get(ref.path)
        write_cb = meta.get("writeData") if meta else None
        refcon = meta.get("writeRefCon") if meta else None

        self.dm.require_array(ref, "setDatab")
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
        fxp = self.fake_xp

        if ref.type != fxp.Type_Data:
            raise TypeError("getDatas on non-byte-array")

        self.dm.require_array(ref, "getDatas")
        arr = ref.value

        if count < 0:
            count = len(arr) - offset

        raw = bytes(arr[offset: offset + count]).split(b"\x00", 1)[0]
        return raw.decode("utf-8", errors="ignore")

    def setDatas(self, dataRef, value: str, offset=0, count=-1) -> None:
        ref = self._resolve_ref(dataRef)
        fxp = self.fake_xp

        if not ref.writable:
            raise PermissionError("DataRef not writable")

        if ref.type != fxp.Type_Data:
            raise TypeError("setDatas on non-byte-array")

        self.dm.require_array(ref, "setDatas")
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
        with self.dm._handles_lock:
            return len(self.dm._handles)

    def getDataRefsByIndex(self, offset: int = 0, count: int = -1) -> List[FakeDataRef]:
        """
        Return a list of dataRef handles by index paging. If count == -1 return all from offset.
        """
        with self.dm._handles_lock:
            keys = list(self.dm._handles.keys())
            if offset < 0:
                offset = 0
            if count == -1:
                selected = keys[offset:]
            else:
                selected = keys[offset: offset + count]
            return [self.dm._handles[k] for k in selected]

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
        fxp = self.fake_xp

        inferred_mask = fxp.Type_Unknown
        if readInt or writeInt:
            inferred_mask |= fxp.Type_Int
        if readFloat or writeFloat:
            inferred_mask |= fxp.Type_Float
        if readDouble or writeDouble:
            inferred_mask |= fxp.Type_Double
        if readFloatArray or writeFloatArray:
            inferred_mask |= fxp.Type_FloatArray
        if readIntArray or writeIntArray:
            inferred_mask |= fxp.Type_IntArray
        if readData or writeData:
            inferred_mask |= fxp.Type_Data

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
        default_value = self.dm.default_value_for(dtype, size)

        existing = self.dm.get_handle(name)
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
            self.dm.add_handle(name, ref)

            # Explicit promotions: registration is authoritative.
            self.dm.promote_type(ref=ref, dtype=dtype, writable=bool(writable_flag))
            self.dm.promote_shape_from_value(ref=ref, value=default_value)

            owner = self.dm._next_owner_id
            self.dm._next_owner_id += 1
            self.dm._accessors[name] = {
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

        self.dm.notify_handle_created(ref)
        return ref

    def unregisterDataAccessor(self, dataRef: FakeDataRef) -> None:
        """
        Unregister a previously registered accessor. Subsequent calls using the handle should raise TypeError.
        """
        if not isinstance(dataRef, FakeDataRef):
            raise TypeError("invalid dataRef")
        stored = self.dm.get_handle(dataRef.path)
        if stored is None or stored is not dataRef:
            raise TypeError("invalid dataRef")
        self.dm._accessors.pop(dataRef.path, None)
        self.dm.del_handle(dataRef.path)

    # -------------------------
    # Helpers for registerDataAccessor
    # -------------------------
    def _bitmask_is_array(self, mask: int) -> bool:
        fxp = self.fake_xp
        return bool(mask & (fxp.Type_FloatArray | fxp.Type_IntArray | fxp.Type_Data))

    def _choose_dtype_from_mask(self, mask: int) -> Tuple[int, bool, int]:
        """
        Choose an xp.Type_* dtype, is_array, and default size from a bitmask.
        Default array size is 1 for scalars, 8 for common arrays (arbitrary).
        """
        fxp = self.fake_xp

        if mask & fxp.Type_FloatArray:
            return fxp.Type_FloatArray, True, 8
        if mask & fxp.Type_IntArray:
            return fxp.Type_IntArray, True, 8
        if mask & fxp.Type_Data:
            return fxp.Type_Data, True, 256
        if mask & fxp.Type_Double:
            return fxp.Type_Double, False, 1
        if mask & fxp.Type_Float:
            return fxp.Type_Float, False, 1
        if mask & fxp.Type_Int:
            return fxp.Type_Int, False, 1

        # Fallback: float scalar
        return fxp.Type_Float, False, 1
