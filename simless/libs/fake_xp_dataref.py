# simless/libs/fake_xp_dataref.py
# ===========================================================================
# FakeXP DataRef subsystem — mirrors XPPython3/X-Plane DataRefInfo fields
#
# CORE INVARIANTS
#   - Public API signatures must MATCH real X-Plane/XPPython3.
#   - Any higher-level normalization is done by DataRefManager.
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from plugins.sshd_extensions.datarefs import DRefType


# ===========================================================================
# FakeDataRef — handle + metadata + value
#   Mirrors XPLMDataRefInfo_t field names:
#   - type
#   - writable
#   - is_array
#   - size
# ===========================================================================

@dataclass(slots=True)
class FakeDataRef:
    path: str
    type: int          # XPLMDataRefTypes
    writable: bool
    is_array: bool
    size: int          # For arrays: length; for scalars: 1
    value: Any
    auto_generated: bool


# ===========================================================================
# FakeXPDataRef — auto-generation using DataRefManager defaults + heuristics
# ===========================================================================

class FakeXPDataRef:

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

    def _init_dataref(self) -> None:
        self._handles: Dict[str, FakeDataRef] = {}
        self._values: Dict[str, Any] = {}
        # Optional: bound DataRefManager so we can honor plugin defaults
        self._dataref_manager = None

    # ----------------------------------------------------------------------
    # Binding to DataRefManager (for simless defaults)
    # ----------------------------------------------------------------------

    def bind_dataref_manager(self, mgr) -> None:
        """
        Called by DataRefManager if available, so FakeXP can see specs/defaults.
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
        Signature is intentionally similar to XPPython3 helpers.
        """
        dtype = DRefType(xp_type)

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
                # For array types without is_array=True, treat as scalar error
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
        If a DataRefManager is bound and has a spec for this path, use its
        default to infer type/shape/value.
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

        # Fallback: scalar float
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

        inferred = self._infer_from_manager(name)
        if inferred is None:
            inferred = self._infer_unmanaged(name)

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
        Mirror XPPython3: return an object with attributes:
          - type
          - writable
          - is_array
          - size

        FakeDataRef already exposes these fields, so we can just return it.
        """
        return handle

    # ----------------------------------------------------------------------
    # Value resolution helper
    # ----------------------------------------------------------------------

    def _resolve_value_ref(self, handle: FakeDataRef | str) -> FakeDataRef:
        """
        Accept either a FakeDataRef handle or a path string, mirroring how
        some code may call the API.
        """
        if isinstance(handle, FakeDataRef):
            return handle

        if handle not in self._handles:
            inferred = self._infer_from_manager(handle)
            if inferred is None:
                inferred = self._infer_unmanaged(handle)

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

    def getDatai(self, handle):
        return int(self._resolve_value_ref(handle).value)

    def setDatai(self, handle, v):
        self._resolve_value_ref(handle).value = int(v)

    def getDataf(self, handle):
        return float(self._resolve_value_ref(handle).value)

    def setDataf(self, handle, v):
        self._resolve_value_ref(handle).value = float(v)

    def getDatad(self, handle):
        return float(self._resolve_value_ref(handle).value)

    def setDatad(self, handle, v):
        self._resolve_value_ref(handle).value = float(v)

    # ----------------------------------------------------------------------
    # Array accessors
    # ----------------------------------------------------------------------

    def getDatavf(self, handle, out, offset, count):
        ref = self._resolve_value_ref(handle)
        arr = ref.value
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = float(arr[offset + i])

    def setDatavf(self, handle, values, offset, count):
        ref = self._resolve_value_ref(handle)
        arr = ref.value
        for i in range(count):
            arr[offset + i] = float(values[i])

    def getDatavi(self, handle, out, offset, count):
        ref = self._resolve_value_ref(handle)
        arr = ref.value
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = int(arr[offset + i])

    def setDatavi(self, handle, values, offset, count):
        ref = self._resolve_value_ref(handle)
        arr = ref.value
        for i in range(count):
            arr[offset + i] = int(values[i])

    def getDatab(self, handle, out, offset, count):
        ref = self._resolve_value_ref(handle)
        arr = ref.value
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = arr[offset + i]

    def setDatab(self, handle, values, offset, count):
        ref = self._resolve_value_ref(handle)
        arr = ref.value
        for i in range(count):
            arr[offset + i] = int(values[i]) & 0xFF

    # ----------------------------------------------------------------------
    # registerDataRef (XPPython3 compatibility)
    # ----------------------------------------------------------------------

    def registerDataRef(self, path, xpType, isArray, writable, defaultValue):
        """
        Mirror XPPython3's registerDataRef signature, but store metadata
        using the same field names as XPLMDataRefInfo_t.
        """
        if path in self._handles:
            return self._handles[path]

        dtype = DRefType(xpType)
        is_array = bool(isArray)

        if isinstance(defaultValue, list):
            size = len(defaultValue)
        elif isinstance(defaultValue, (bytes, bytearray)):
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
