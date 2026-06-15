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
    #  INTERNAL CANONICAL HELPERS (strongly typed, prod-spec)
    # ================================================================
    def _get_scalar(
            self,
            dr: XPLMDataRef,
            expected_type: XPLMDataTypeID | int,
    ) -> float | int:
        """
        Canonical scalar getter:
          • resolve handle
          • if accessor: use read_scalar(ref.read_refcon)
          • else: dummy-shape and return internal value
        """
        ref = self.dm.require_handle(dr)

        # Accessor-backed scalar
        if ref.read_scalar is not None:
            return ref.read_scalar(ref.read_refcon)

        # Internal scalar
        if ref.dummy:
            self.dm.shape_dummy(ref, expected_type)

        return self.dm.get_value(ref)

    def _set_scalar(
            self,
            dr: XPLMDataRef,
            expected_type: XPLMDataTypeID | int,
            value: float | int,
    ) -> None:
        """
        Canonical scalar setter:
          • resolve handle
          • if accessor: use write_scalar(ref.write_refcon, value)
          • else: dummy-shape and update internal value
        """
        ref = self.dm.require_handle(dr)

        # Accessor-backed scalar
        if ref.write_scalar is not None:
            ref.write_scalar(ref.write_refcon, value)
            return

        # Internal scalar
        if ref.dummy:
            self.dm.shape_dummy(ref, expected_type, value=value)
            return

        self.dm.update_value(ref, value)

    def _get_array(
            self,
            dr: XPLMDataRef,
            expected_type: XPLMDataTypeID | int,
            out: Optional[MutableSequence[float | int]],
            offset: int,
            count: int,
    ) -> int:
        """
        Canonical array getter (prod-spec):

          ACCESSOR-BACKED ARRAYS:
            • out=None → return length
            • out!=None → plugin read into temp buffer, then copy into out[offset+i]
            • negative count → read to end
            • never pass caller's buffer directly to plugin

          INTERNAL ARRAYS:
            • out=None → return size
            • out!=None → copy into out[offset+i]
            • negative count → read to end
        """
        ref = self.dm.require_handle(dr)

        # ACCESSOR-BACKED ARRAY
        if ref.read_array is not None:

            # Normalize count BEFORE calling accessor
            if count < 0:
                if ref.size:
                    count = ref.size - offset
                else:
                    probe = [0.0] * 4096
                    try:
                        n = ref.read_array(ref.read_refcon, probe, offset, 4096)
                    except Exception as exc:
                        raise ValueError(f"{ref.path}: accessor array read failed") from exc
                    count = max(0, n - offset)

            # out=None → return length
            if out is None:
                tmp = [0.0] * count
                try:
                    n = ref.read_array(ref.read_refcon, tmp, offset, count)
                except Exception as exc:
                    raise ValueError(f"{ref.path}: accessor array read failed") from exc
                return n

            # --- STRICT: caller buffer must be large enough ---
            if offset + count > len(out):
                raise ValueError(
                    f"{ref.path}: accessor array read would write past end of caller buffer"
                )

            # Read into temp buffer
            tmp = [0.0] * count
            try:
                n = ref.read_array(ref.read_refcon, tmp, offset, count)
            except Exception as exc:
                raise ValueError(f"{ref.path}: accessor array read failed") from exc

            # Copy into caller buffer at offset
            for i in range(n):
                out[offset + i] = tmp[i]

            return n

        # ------------------------------------------------------------
        # INTERNAL ARRAY
        # ------------------------------------------------------------
        if ref.dummy:
            self.dm.shape_dummy(ref, expected_type)

        if out is None:
            return ref.size

        if count < 0:
            count = ref.size - offset

        vals = self.dm.get_value(ref, offset=offset, count=count)
        n = len(vals)

        if offset + n > len(out):
            raise ValueError("array read past end of caller buffer")

        # Write into out[offset + i]
        for i in range(n):
            out[offset + i] = vals[i]

        return n

    def _set_array(
            self,
            dr: XPLMDataRef,
            expected_type: int,
            values: Sequence[float | int],
            offset: int,
            count: int,
    ) -> None:
        """
        Canonical array setter (XPPython3 semantics):

        ACCESSOR-BACKED ARRAYS (dynamic):
            • Caller must supply at least `count` values.
            • FakeXP does NOT bounds-check using the plugin's read accessor.
            • Any exception raised by the plugin's read/write accessors MUST be
              normalized to ValueError (never leak IndexError, TypeError, etc.).
            • If plugin read/write fails → ValueError.

        INTERNAL ARRAYS (fixed-size):
            • Bounds are enforced strictly.
            • Writing past end → RuntimeError.
            • Dummy refs: shape is established on first write.

        This matches XPPython3 behavior exactly.
        """

        ref = self.dm.require_handle(dr)

        # ------------------------------------------------------------
        # ACCESSOR-BACKED ARRAY (dynamic)
        # ------------------------------------------------------------
        if ref.write_array is not None:

            # Caller must supply at least `count` values
            if len(values) < count:
                raise ValueError(
                    f"{ref.path}: accessor array write requires at least {count} values"
                )

            try:
                # Optional read: plugin may enforce its own bounds
                if ref.read_array is not None:
                    probe = [0.0] * count
                    ref.read_array(ref.read_refcon, probe, offset, count)

                # Actual write
                ref.write_array(ref.write_refcon, values, offset, count)

            except Exception as exc:
                # Normalize ANY plugin exception to ValueError
                raise ValueError(
                    f"{ref.path}: accessor array write failed"
                ) from exc

            return

        # ------------------------------------------------------------
        # INTERNAL ARRAY (fixed-size)
        # ------------------------------------------------------------
        if ref.dummy:
            self.dm.shape_dummy(ref, expected_type, value=list(values))
            return

        if offset + count > ref.size:
            raise ValueError(f"{ref.path}: setDatavf would write past end of dataRef")

        buf = ref.value
        for i in range(count):
            buf[offset + i] = values[i]

    # ================================================================
    #  SCALAR GETTERS (thin wrappers)
    # ================================================================

    def getDatai(self, dr: XPLMDataRef) -> int:
        return int(self._get_scalar(dr, self.fake_xp.Type_Int))

    def getDataf(self, dr: XPLMDataRef) -> float:
        return float(self._get_scalar(dr, self.fake_xp.Type_Float))

    def getDatad(self, dr: XPLMDataRef) -> float:
        return self.getDataf(dr)

    def getDatab(self, dr: XPLMDataRef) -> int:
        return int(self._get_scalar(dr, self.fake_xp.Type_Data))

    # ================================================================
    #  ARRAY GETTERS (thin wrappers)
    # ================================================================

    def getDatavi(
            self,
            dr: XPLMDataRef,
            out: Optional[List[int]],
            offset: int,
            count: int,
    ) -> int:
        return self._get_array(dr, self.fake_xp.Type_IntArray, out, offset, count)

    def getDatavf(
            self,
            dr: XPLMDataRef,
            out: Optional[List[float]],
            offset: int,
            count: int,
    ) -> int:
        return self._get_array(dr, self.fake_xp.Type_FloatArray, out, offset, count)

    # ================================================================
    #  SCALAR SETTERS (thin wrappers)
    # ================================================================

    def setDatai(self, dr: XPLMDataRef, v: int) -> None:
        self._set_scalar(dr, self.fake_xp.Type_Int, v)

    def setDataf(self, dr: XPLMDataRef, v: float) -> None:
        self._set_scalar(dr, self.fake_xp.Type_Float, v)

    def setDatad(self, dr: XPLMDataRef, v: float) -> None:
        self.setDataf(dr, v)

    def setDatab(self, dr: XPLMDataRef, v: int) -> None:
        self._set_scalar(dr, self.fake_xp.Type_Data, v & 0xFF)

    # ================================================================
    #  ARRAY SETTERS (thin wrappers)
    # ================================================================

    def setDatavi(
            self,
            dr: XPLMDataRef,
            values: Sequence[int],
            offset: int,
            count: int,
    ) -> None:
        self._set_array(dr, self.fake_xp.Type_IntArray, values, offset, count)

    def setDatavf(
            self,
            dr: XPLMDataRef,
            values: Sequence[float],
            offset: int,
            count: int,
    ) -> None:
        self._set_array(dr, self.fake_xp.Type_FloatArray, values, offset, count)

    # ============================================================
    # DATA BYTE-ARRAY GETTER (getDatabv)
    # ============================================================
    def getDatabv(
            self,
            dr: XPLMDataRef,
            out: list[int] | None,
            offset: int,
            count: int
    ) -> int:
        """
        Strongly typed DATA byte-array getter.

        • Accessor-backed:
              - count < 0 → full length (probe)
              - out=None  → return length
              - out!=None → read into caller buffer
        • Internal:
              - out=None  → return len(ref.value)
              - count < 0 → read to end
              - out!=None → copy bytes
        """
        ref = self.fake_xp.dataref_manager.require_handle(dr)

        # -------------------------
        # Accessor-backed DATA
        # -------------------------
        if ref.read_array is not None:
            # Normalize count
            if count < 0:
                probe = [0] * 4096
                n = ref.read_array(ref.read_refcon, probe, offset, 4096)
                count = max(0, n - offset)

            if out is None:
                tmp = [0] * count
                n = ref.read_array(ref.read_refcon, tmp, offset, count)
                return n

            return ref.read_array(ref.read_refcon, out, offset, count)

        # -------------------------
        # Internal DATA
        # -------------------------
        if ref.dummy:
            self.fake_xp.dataref_manager.shape_dummy(ref, self.fake_xp.Type_Data)

        buf: bytearray = ref.value
        total = len(buf)

        if out is None:
            return total

        if offset < 0 or offset > total:
            raise ValueError("invalid offset for getDatabv")

        if count < 0:
            count = total - offset

        end = min(offset + count, total)
        n = end - offset

        if n > len(out):
            raise ValueError("array read past end of caller buffer")

        for i in range(n):
            out[i] = buf[offset + i]

        return n

    # ============================================================
    # DATA BYTE-ARRAY SETTER (setDatabv)
    # ============================================================
    def setDatabv(
            self,
            dr: XPLMDataRef,
            values: list[int],
            offset: int,
            count: int
    ) -> None:
        """
        Strongly typed DATA byte-array setter.

        • Accessor-backed:
              - len(values) >= count or ValueError
              - write_array(refcon, values, offset, count)
        • Internal:
              - count < 0 → count = len(values)
              - Bounds checked against len(ref.value)
              - Writes go through update_value()
        """
        ref = self.fake_xp.dataref_manager.require_handle(dr)

        # -------------------------
        # Accessor-backed DATA
        # -------------------------
        if ref.write_array is not None:
            if count < 0:
                count = len(values)
            if len(values) < count:
                raise ValueError(f"{ref.path}: accessor DATA write requires {count} bytes")
            ref.write_array(ref.write_refcon, values, offset, count)
            return

        # -------------------------
        # Internal DATA
        # -------------------------
        if ref.dummy:
            self.fake_xp.dataref_manager.shape_dummy(ref, self.fake_xp.Type_Data)

        buf: bytearray = ref.value
        total = len(buf)

        if count < 0:
            count = len(values)

        if offset < 0 or offset > total:
            raise ValueError("invalid offset for setDatabv")

        if offset + count > total:
            raise ValueError("setDatabv would write past end of DATA buffer")

        # update_value handles canonical write + timestamp
        self.fake_xp.dataref_manager.update_value(ref, values, offset=offset, count=count)

    # ============================================================
    # STRING GETTER (getDatas)
    # ============================================================
    def getDatas(
            self,
            dr: XPLMDataRef,
            offset: int = 0,
            count: int = -1
    ) -> str:
        """
        Strongly typed DATA string getter.

        • Returns UTF‑8 decoded string
        • Stops at first NUL byte
        • Uses accessor if present
        """
        ref = self.fake_xp.dataref_manager.require_handle(dr)

        # Accessor-backed
        if ref.read_array is not None:
            if count < 0:
                probe = [0] * 4096
                n = ref.read_array(ref.read_refcon, probe, offset, 4096)
                count = max(0, n - offset)

            tmp = [0] * count
            n = ref.read_array(ref.read_refcon, tmp, offset, count)
            raw = bytes(tmp[:n])

        else:
            # Internal
            if ref.dummy:
                self.fake_xp.dataref_manager.shape_dummy(ref, self.fake_xp.Type_Data)

            buf: bytearray = ref.value
            total = len(buf)

            if offset < 0 or offset > total:
                raise ValueError("invalid offset for getDatas")

            if count < 0:
                raw = bytes(buf[offset:])
            else:
                raw = bytes(buf[offset:offset + count])

        # Null-terminate
        nul = raw.find(b"\x00")
        if nul >= 0:
            raw = raw[:nul]

        return raw.decode("utf-8", errors="ignore")

    # ============================================================
    # STRING SETTER (setDatas)
    # ============================================================
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
        • Writes bytes into DATA buffer
        • Uses accessor if present
        """
        ref = self.fake_xp.dataref_manager.require_handle(dr)
        encoded = value.encode("utf-8")

        # Accessor-backed
        if ref.write_array is not None:
            if count < 0:
                count = len(encoded)
            if len(encoded) < count:
                raise ValueError(f"{ref.path}: accessor DATA write requires {count} bytes")
            ref.write_array(ref.write_refcon, encoded, offset, count)
            return

        # Internal
        if ref.dummy:
            self.fake_xp.dataref_manager.shape_dummy(ref, self.fake_xp.Type_Data)

        buf: bytearray = ref.value
        total = len(buf)

        if offset < 0 or offset > total:
            raise ValueError("invalid offset for setDatas")

        if count < 0:
            count = total - offset

        if offset + count > total:
            raise ValueError("setDatas would write past end of DATA buffer")

        self.fake_xp.dataref_manager.update_value(ref, encoded, offset=offset, count=count)

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
