# simless/libs/fake_xp_dataref.py
# ===========================================================================
# FakeXP DataRef subsystem — mirrors the XPPython3 DataRef API
#
# CORE INVARIANTS
#   • Public API signatures MUST MATCH real X‑Plane / XPPython3.
#   • FakeXP performs NO normalization or inference beyond type/shape/value.
#   • DataRefManager (if bound) provides authoritative defaults/specs.
#   • All values are stored deterministically; no hidden state.
#
# ARCHITECTURAL NOTES
#   • XPPython3 exposes DataRefInfo via XPLMDataRefInfo_t with fields:
#         type, writable, is_array, size
#     FakeDataRef mirrors these exactly.
#
#   • FakeXPDataRef supports:
#         – explicit registration (fake_register_dataref)
#         – auto‑generation honoring DataRefManager defaults
#         – unmanaged heuristics for missing specs
#
#   • Array accessors follow XPPython3 semantics:
#         – out=None returns array length
#         – otherwise caller must provide a mutable sequence
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, List, Optional, MutableSequence, Sequence, Union

from simless.libs.fake_xp_interface import FakeXPInterface


# ===========================================================================
# DRefType — simless‑local enum (mirrors production values)
# ===========================================================================
class DRefType(IntEnum):
    INT         = 1
    FLOAT       = 2
    DOUBLE      = 4
    FLOAT_ARRAY = 8
    INT_ARRAY   = 16
    BYTE_ARRAY  = 32


# ===========================================================================
# FakeDataRef — handle + metadata + value
#   Mirrors XPLMDataRefInfo_t field names:
#     • type
#     • writable
#     • is_array
#     • size
# ===========================================================================
@dataclass(slots=True)
class FakeDataRef:
    path: str
    type: int                 # XPLMDataRefTypes
    writable: bool
    is_array: bool
    size: int                 # For arrays: length; for scalars: 1
    value: Any                # Scalar, list, or bytearray
    auto_generated: bool      # True if inferred, False if explicitly registered


# ===========================================================================
# FakeXPDataRef — auto-generation using DataRefManager defaults + heuristics
# ===========================================================================
class FakeXPDataRef:
    xp: FakeXPInterface  # established in FakeXP

    public_api_names = [
        "fake_register_dataref",
        "findDataRef",
        "getDataRefInfo",
        "getDatai",
        "setDatai",
        "getDataf",
        "setDataf",
        "getDatad",
        "setDatad",
        "getDatavf",
        "setDatavf",
        "getDatavi",
        "setDatavi",
        "getDatab",
        "setDatab",
        "registerDataRef",
    ]

    # ----------------------------------------------------------------------
    # Initialization
    # ----------------------------------------------------------------------
    def _init_dataref(self) -> None:
        self._handles: Dict[str, FakeDataRef] = {}
        self._values: Dict[str, Any] = {}
        self._dataref_manager: Optional[Any] = None

    # ----------------------------------------------------------------------
    # Binding to DataRefManager (for simless defaults)
    # ----------------------------------------------------------------------
    def bind_dataref_manager(self, mgr: Any) -> None:
        """
        Bind DataRefManager so FakeXP can honor plugin-defined defaults.
        """
        self._dataref_manager = mgr

    # ----------------------------------------------------------------------
    # Explicit registration (test helpers / XPPython3 compatibility)
    # ----------------------------------------------------------------------
    def fake_register_dataref(
        self,
        path: str,
        *,
        xp_type: int,
        is_array: bool = False,
        size: int = 1,
        writable: bool = True,
    ) -> FakeDataRef:
        """
        Explicitly register a DataRef with full control over metadata.
        Signature intentionally mirrors XPPython3 helpers.
        """
        dtype = DRefType(xp_type)

        # Allocate default storage
        if is_array:
            if dtype == DRefType.FLOAT_ARRAY:
                value = [0.0] * size
            elif dtype == DRefType.INT_ARRAY:
                value = [0] * size
            elif dtype == DRefType.BYTE_ARRAY:
                value = bytearray(size)
            else:
                raise TypeError(f"Scalar dtype {dtype} cannot be registered as array")
        else:
            if dtype == DRefType.FLOAT:
                value = 0.0
            elif dtype == DRefType.INT:
                value = 0
            elif dtype == DRefType.DOUBLE:
                value = 0.0
            else:
                raise TypeError(f"Array dtype {dtype} must be registered with is_array=True")

        ref = FakeDataRef(
            path=path,
            type=int(dtype),
            writable=writable,
            is_array=is_array,
            size=size,
            value=value,
            auto_generated=False,
        )

        self._handles[path] = ref
        self._values[path] = value
        return ref

    # ----------------------------------------------------------------------
    # Auto-generation honoring DataRefManager defaults
    # ----------------------------------------------------------------------
    def _infer_from_manager(self, name: str) -> Optional[Dict[str, Any]]:
        """
        If DataRefManager has a spec for this path, infer type/shape/value.
        """
        mgr = self._dataref_manager
        if mgr is None:
            return None

        spec = mgr.get_spec(name) if hasattr(mgr, "get_spec") else mgr.specs.get(name)
        if spec is None:
            return None

        default = spec.default

        if isinstance(default, list):
            return {
                "dtype": DRefType.FLOAT_ARRAY,
                "is_array": True,
                "size": len(default),
                "value": [0.0] * len(default),
            }

        if isinstance(default, (bytes, bytearray)):
            return {
                "dtype": DRefType.BYTE_ARRAY,
                "is_array": True,
                "size": len(default),
                "value": bytearray(len(default)),
            }

        # Scalar fallback
        return {
            "dtype": DRefType.FLOAT,
            "is_array": False,
            "size": 1,
            "value": 0.0,
        }

    def _infer_unmanaged(self, name: str) -> Dict[str, Any]:
        """
        Heuristic for unmanaged DataRefs (no spec in DataRefManager).
        """
        is_array = name.endswith("s") or "array" in name.lower()
        if is_array:
            return {
                "dtype": DRefType.FLOAT_ARRAY,
                "is_array": True,
                "size": 8,
                "value": [0.0] * 8,
            }
        return {
            "dtype": DRefType.FLOAT,
            "is_array": False,
            "size": 1,
            "value": 0.0,
        }

    # ----------------------------------------------------------------------
    # Lookup
    # ----------------------------------------------------------------------
    def findDataRef(self, name: str) -> FakeDataRef | None:
        """
        Mirror XPPython3: return a handle object or None.
        """
        if name in self._handles:
            return self._handles[name]

        inferred = self._infer_from_manager(name) or self._infer_unmanaged(name)

        ref = FakeDataRef(
            path=name,
            type=int(inferred["dtype"]),
            writable=True,
            is_array=inferred["is_array"],
            size=inferred["size"],
            value=inferred["value"],
            auto_generated=True,
        )
        self._handles[name] = ref
        self._values[name] = ref.value
        return ref

    def getDataRefInfo(self, handle: FakeDataRef) -> FakeDataRef:
        """
        Mirror XPPython3: return an object exposing:
          • type
          • writable
          • is_array
          • size
        """
        return handle

    # ----------------------------------------------------------------------
    # Value resolution helper
    # ----------------------------------------------------------------------
    def _resolve_value_ref(self, handle: Union[FakeDataRef, str]) -> FakeDataRef:
        """
        Accept either a FakeDataRef handle or a path string.
        """
        if isinstance(handle, FakeDataRef):
            return handle

        if handle not in self._handles:
            inferred = self._infer_from_manager(handle) or self._infer_unmanaged(handle)
            ref = FakeDataRef(
                path=handle,
                type=int(inferred["dtype"]),
                writable=True,
                is_array=inferred["is_array"],
                size=inferred["size"],
                value=inferred["value"],
                auto_generated=True,
            )
            self._handles[handle] = ref
            self._values[handle] = ref.value
            return ref

        return self._handles[handle]

    # ----------------------------------------------------------------------
    # Scalar accessors
    # ----------------------------------------------------------------------
    def getDatai(self, handle: Union[FakeDataRef, str]) -> int:
        return int(self._resolve_value_ref(handle).value)

    def setDatai(self, handle: Union[FakeDataRef, str], v: Any) -> None:
        self._resolve_value_ref(handle).value = int(v)

    def getDataf(self, handle: Union[FakeDataRef, str]) -> float:
        return float(self._resolve_value_ref(handle).value)

    def setDataf(self, handle: Union[FakeDataRef, str], v: Any) -> None:
        self._resolve_value_ref(handle).value = float(v)

    def getDatad(self, handle: Union[FakeDataRef, str]) -> float:
        return float(self._resolve_value_ref(handle).value)

    def setDatad(self, handle: Union[FakeDataRef, str], v: Any) -> None:
        self._resolve_value_ref(handle).value = float(v)

    # ----------------------------------------------------------------------
    # Array accessors
    # ----------------------------------------------------------------------
    def getDatavf(
        self,
        handle: Union[FakeDataRef, str],
        out: Optional[MutableSequence[float]],
        offset: int,
        count: int,
    ) -> Optional[int]:
        ref = self._resolve_value_ref(handle)
        arr: List[float] = ref.value
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = float(arr[offset + i])
        return None

    def setDatavf(
        self,
        handle: Union[FakeDataRef, str],
        values: MutableSequence[float],
        offset: int,
        count: int,
    ) -> None:
        ref = self._resolve_value_ref(handle)
        arr: List[float] = ref.value
        for i in range(count):
            arr[offset + i] = float(values[i])

    def getDatavi(
        self,
        handle: Union[FakeDataRef, str],
        out: Optional[MutableSequence[int]],
        offset: int,
        count: int,
    ) -> Optional[int]:
        ref = self._resolve_value_ref(handle)
        arr: List[int] = ref.value
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = int(arr[offset + i])
        return None

    def setDatavi(
        self,
        handle: Union[FakeDataRef, str],
        values: MutableSequence[int],
        offset: int,
        count: int,
    ) -> None:
        ref = self._resolve_value_ref(handle)
        arr: List[int] = ref.value
        for i in range(count):
            arr[offset + i] = int(values[i])

    def getDatab(
        self,
        handle: Union[FakeDataRef, str],
        out: Optional[bytearray],
        offset: int,
        count: int,
    ) -> Optional[int]:
        ref = self._resolve_value_ref(handle)
        arr: bytearray = ref.value
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = arr[offset + i]
        return None

    def setDatab(
        self,
        handle: Union[FakeDataRef, str],
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None:
        ref = self._resolve_value_ref(handle)
        arr: bytearray = ref.value
        for i in range(count):
            arr[offset + i] = int(values[i]) & 0xFF

    # ----------------------------------------------------------------------
    # registerDataRef (XPPython3 compatibility)
    # ----------------------------------------------------------------------
    def registerDataRef(
        self,
        path: str,
        xpType: int,
        isArray: bool,
        writable: bool,
        defaultValue: Any,
    ) -> FakeDataRef:
        """
        Mirror XPPython3's registerDataRef signature.
        """
        if path in self._handles:
            return self._handles[path]

        dtype = DRefType(xpType)
        is_array = bool(isArray)

        if isinstance(defaultValue, (list, bytes, bytearray)):
            size = len(defaultValue)
        else:
            size = 1

        ref = FakeDataRef(
            path=path,
            type=int(dtype),
            writable=bool(writable),
            is_array=is_array,
            size=size,
            value=defaultValue,
            auto_generated=False,
        )

        self._handles[path] = ref
        self._values[path] = defaultValue
        return ref
