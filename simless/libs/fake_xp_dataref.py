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

from typing import Any, Callable, List, MutableSequence, Optional, Sequence, TYPE_CHECKING, Tuple, cast

from simless.libs.dataref import DataRefManager
from xp_typing import XPLMDataRef, XPLMDataRefInfo_t, XPLMDataTypeID

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
    def findDataRef(self, name: str) -> Optional[XPLMDataRef]:
        existing = self.dm.get_handle(name)
        if existing is not None:
            return existing.df_id

        return self.dm.add_handle(name).df_id

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def getDataRefTypes(self, dataRef: XPLMDataRef) -> XPLMDataTypeID | int:
        return self.dm.require_handle(dataRef).type

    def getDataRefInfo(self, dataRef: XPLMDataRef) -> XPLMDataRefInfo_t:
        ref = self.dm.require_handle(dataRef)

        # Base XPLM fields
        info = XPLMDataRefInfo_t(
            name=ref.path,
            type=ref.type,
            writable=bool(ref.writable),
            owner=0,
        )

        # XPLMGetDataRefInfo adds these dynamically
        setattr(info, "is_array", ref.is_array)

        # Production semantics:
        #   • Dummy refs report size = 0
        #   • Promoted refs report actual size
        size = ref.size if not ref.dummy else 0
        setattr(info, "size", size)

        return info

    def canWriteDataRef(self, dataRef: XPLMDataRef) -> bool:
        return self.dm.require_handle(dataRef).writable

    def isDataRefGood(self, dataRef: XPLMDataRef) -> bool:
        try:
            self.dm.require_handle(dataRef)
            return True
        except Exception:
            return False

    # ================================================================
    #  SCALAR GETTERS (thin wrappers)
    # ================================================================

    def getDatai(self, dr: XPLMDataRef) -> int:
        return int(self.dm.get_value(dr, self.fake_xp.Type_Int))

    def getDataf(self, dr: XPLMDataRef) -> float:
        return float(self.dm.get_value(dr, self.fake_xp.Type_Float))

    def getDatad(self, dr: XPLMDataRef) -> float:
        return self.getDataf(dr)

    # ================================================================
    #  ARRAY GETTERS (thin wrappers)
    # ================================================================

    def getDatavi(
            self,
            dr: XPLMDataRef,
            values: Optional[List[int]] = None,
            offset: int = 0,
            count: int = -1
    ) -> int:
        return self.dm.get_value(dr, self.fake_xp.Type_IntArray, offset, count, values)

    def getDatavf(
            self,
            dr: XPLMDataRef,
            values: Optional[List[float]] = None,
            offset: int = 0,
            count: int = -1
    ) -> int:
        return self.dm.get_value(dr, self.fake_xp.Type_FloatArray, offset, count, values)

    def getDatab(
            self,
            dr: XPLMDataRef,
            values: Optional[List[int]] = None,
            offset: int = 0,
            count: int = -1
    ) -> int:
        return self.dm.get_value(dr, self.fake_xp.Type_Data, offset, count, values)

    # ================================================================
    #  SCALAR SETTERS (thin wrappers)
    # ================================================================

    def setDatai(self, dr: XPLMDataRef, v: int) -> None:
        self.dm.update_value(dr, self.fake_xp.Type_Int, v)

    def setDataf(self, dr: XPLMDataRef, v: float) -> None:
        self.dm.update_value(dr, self.fake_xp.Type_Float, v)

    def setDatad(self, dr: XPLMDataRef, v: float) -> None:
        self.setDataf(dr, v)

    # ================================================================
    #  ARRAY SETTERS (thin wrappers)
    # ================================================================

    def setDatavi(
            self,
            dr: XPLMDataRef,
            values: Sequence[int],
            offset: int = 0,
            count: int = -1
    ) -> int:
        written = self.dm.update_value(dr, self.fake_xp.Type_IntArray, values, offset, count)
        assert written is not None
        return written

    def setDatavf(
            self,
            dr: XPLMDataRef,
            values: Sequence[float],
            offset: int = 0,
            count: int = -1
    ) -> int:
        written = self.dm.update_value(dr, self.fake_xp.Type_FloatArray, values, offset, count)
        assert written is not None
        return written

    def setDatab(
            self,
            dr: XPLMDataRef,
            values: Sequence[int],
            offset: int = 0,
            count: int = -1
    ) -> int:
        written = self.dm.update_value(dr, self.fake_xp.Type_Data, values, offset, count)
        assert written is not None
        return written

    def getDatas(
            self,
            dr: XPLMDataRef,
            offset: int = 0,
            count: int = -1
    ) -> str:
        """
        Strongly typed DATA string getter.

        • Uses universal get_value() with a buffer
        • Accessor-backed DATA arrays bypass clipping
        • Canonical DATA arrays clip
        • Stops at first NUL
        • Returns UTF‑8 decoded string
        """
        buf: list[int] = []

        n = self.fake_xp.dataref_manager.get_value(
            dr,
            expected_type=self.fake_xp.Type_Data,
            offset=offset,
            count=count,
            values=buf,
        )

        raw = bytes(buf[:n])

        nul = raw.find(b"\x00")
        if nul >= 0:
            raw = raw[:nul]

        return raw.decode("utf-8", errors="ignore")

    def setDatas(
            self,
            dr: XPLMDataRef,
            value: str,
            offset: int = 0,
            count: int = -1
    ) -> None:
        """
        Strongly typed DATA string setter.

        • Encodes string as UTF‑8
        • Uses universal update_value()
        • Accessor-backed DATA arrays bypass canonical logic
        • Canonical DATA arrays clip and cast via update_value()
        """
        encoded = value.encode("utf-8")

        self.fake_xp.dataref_manager.update_value(
            dr=dr,
            expected_type=self.fake_xp.Type_Data,
            value=encoded,
            offset=offset,
            count=count,
        )

    # -------------------------
    # Registration / publishing
    # -------------------------
    def registerDataAccessor(
            self,
            name: str,
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
    ) -> XPLMDataRef:
        """
        Register callbacks and return a dataref handle. Signature mirrors XPLMRegisterDataAccessor.
        If dataType == 0 or writable == -1, compute from provided callbacks.
        """
        fxp = self.fake_xp

        # ------------------------------------------------------------
        # 1. Infer mask if dataType == 0
        # ------------------------------------------------------------
        inferred_mask = fxp.Type_Unknown
        if readInt or writeInt:
            inferred_mask |= fxp.Type_Int
        if readFloat or writeFloat:
            inferred_mask |= fxp.Type_Float
        if readDouble or writeDouble:
            inferred_mask |= fxp.Type_Double
        if readIntArray or writeIntArray:
            inferred_mask |= fxp.Type_IntArray
        if readFloatArray or writeFloatArray:
            inferred_mask |= fxp.Type_FloatArray
        if readData or writeData:
            inferred_mask |= fxp.Type_Data

        mask = dataType if dataType != 0 else inferred_mask

        # ------------------------------------------------------------
        # 2. Determine writable flag
        # ------------------------------------------------------------
        if writable != -1:
            writable_flag = bool(writable)
        else:
            writable_flag = any((
                writeInt, writeFloat, writeDouble,
                writeIntArray, writeFloatArray, writeData
            ))

        # ------------------------------------------------------------
        # 3. Determine dtype + shape
        # ------------------------------------------------------------
        dtype, is_array, size = self._choose_dtype_from_mask(mask)

        # ------------------------------------------------------------
        # 4. Select correct callbacks based on dtype
        # ------------------------------------------------------------
        read_cb, write_cb = self._select_callbacks_for_dtype(
            dtype,
            readInt=readInt, writeInt=writeInt,
            readFloat=readFloat, writeFloat=writeFloat,
            readDouble=readDouble, writeDouble=writeDouble,
            readIntArray=readIntArray, writeIntArray=writeIntArray,
            readFloatArray=readFloatArray, writeFloatArray=writeFloatArray,
            readData=readData, writeData=writeData,
        )

        # ------------------------------------------------------------
        # 5. Create or retrieve the FakeDataRef
        # ------------------------------------------------------------
        ref = self.dm.get_handle(name)
        if ref is None:
            ref = self.dm.add_handle(name)

        # ------------------------------------------------------------
        # 6. Promote dummy → accessor-backed DataRef
        # ------------------------------------------------------------
        self.dm.promote(
            ref=ref,
            dtype=dtype,
            writable=writable_flag,
            array_size=size,
            read_scalar=read_cb if not is_array else None,
            write_scalar=write_cb if not is_array else None,
            read_array=read_cb if is_array else None,
            write_array=write_cb if is_array else None,
        )

        # ------------------------------------------------------------
        # 7. Store refcons directly on the FakeDataRef
        # ------------------------------------------------------------
        ref.read_refcon = readRefCon
        ref.write_refcon = writeRefCon

        return ref.df_id

    def unregisterDataAccessor(self, dataRef: XPLMDataRef) -> None:
        """
        Unregister a previously registered accessor.

        Prod semantics:
          • Scalar accessor-backed datarefs have no internal storage → delete.
          • Array accessor-backed datarefs:
                - If promoted (size > 0) → keep and revert to internal storage.
                - If not promoted → delete.
        """
        ref = self.fake_xp.dataref_manager.require_handle(dataRef)

        # Remove accessor callbacks
        ref.read_scalar = None
        ref.write_scalar = None
        ref.read_array = None
        ref.write_array = None
        ref.read_refcon = None
        ref.write_refcon = None

        if ref.is_array:
            # Array: keep only if promoted (size > 0)
            if ref.size and ref.size > 0:
                return  # keep internal storage

        self.fake_xp.dataref_manager.del_handle(dataRef)

    # -------------------------
    # Helpers for registerDataAccessor
    # -------------------------
    def _select_callbacks_for_dtype(self, dtype, *,
                                    readInt, writeInt,
                                    readFloat, writeFloat,
                                    readDouble, writeDouble,
                                    readIntArray, writeIntArray,
                                    readFloatArray, writeFloatArray,
                                    readData, writeData):
        xp = self.fake_xp

        # Scalar types
        if dtype & xp.Type_Int:
            return readInt, writeInt
        if dtype & xp.Type_Float:
            return readFloat, writeFloat
        if dtype & xp.Type_Double:
            return readDouble, writeDouble

        # Array types
        if dtype & xp.Type_IntArray:
            return readIntArray, writeIntArray
        if dtype & xp.Type_FloatArray:
            return readFloatArray, writeFloatArray
        if dtype & xp.Type_Data:
            return readData, writeData

        return None, None

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
