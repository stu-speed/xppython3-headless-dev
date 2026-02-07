# simless/libs/fake_xp/datarefs.py
# ===========================================================================
# DataRef subsystem — tables, FakeDataRefInfo, and xp.* DataRef API.
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from plugins.sshd_extensions.datarefs import DRefType, DataRefManager  # type: ignore[import]


@dataclass(slots=True)
class FakeDataRefInfo:
    path: str
    xp_type: int
    writable: bool
    is_array: bool
    size: int
    dummy: bool
    value: Any

    def __repr__(self) -> str:
        kind = "array" if self.is_array else "scalar"
        dummy = " dummy" if self.dummy else ""
        return f"<FakeDataRefInfo {self.path} ({kind}, type={self.xp_type}, size={self.size}{dummy})>"


class DataRefAPI:
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
        "getDatvi",
        "setDatvi",
        "getDatab",
        "setDatab",
        "registerDataRef",
    ]

    def __init__(self, fakexp: Any) -> None:
        self.xp = fakexp
        self._handles: Dict[str, FakeDataRefInfo] = {}
        self._dummy_refs: Dict[str, FakeDataRefInfo] = {}
        self._values: Dict[str, Any] = {}
        self._datarefs: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # Simless auto-registration                                          #
    # ------------------------------------------------------------------ #
    def fake_register_dataref(
        self,
        path: str,
        *,
        xp_type: int,
        is_array: bool = False,
        size: int = 1,
        writable: bool = True,
    ) -> FakeDataRefInfo:
        dtype = DRefType(xp_type)

        if dtype == DRefType.FLOAT_ARRAY:
            value: Any = [0.0] * size
        elif dtype == DRefType.INT_ARRAY:
            value = [0] * size
        elif dtype == DRefType.BYTE_ARRAY:
            value = bytearray(size)
        elif dtype == DRefType.FLOAT:
            value = 0.0
        elif dtype == DRefType.INT:
            value = 0
        elif dtype == DRefType.DOUBLE:
            value = 0.0
        else:
            raise TypeError(f"Unsupported dtype {dtype} for {path}")

        ref = FakeDataRefInfo(
            path=path,
            xp_type=int(dtype),
            writable=writable,
            is_array=is_array,
            size=size,
            dummy=False,
            value=value,
        )

        self._handles[path] = ref
        self._values[path] = value
        self.xp._dbg(f"fake_register_dataref('{path}', type={int(dtype)}, array={is_array}, size={size})")
        return ref

    # ------------------------------------------------------------------ #
    # DataRef API                                                        #
    # ------------------------------------------------------------------ #
    def findDataRef(self, name: str) -> FakeDataRefInfo | None:
        if "[" in name or "]" in name:
            self.xp._dbg(f"findDataRef rejected invalid array element syntax: '{name}'")
            return None

        if name in self._handles:
            return self._handles[name]

        if name in self._datarefs:
            ref_dict = self._datarefs[name]
            return ref_dict.get("handle")  # type: ignore[return-value]

        is_array = name.endswith("s") or "array" in name.lower()

        if is_array:
            dtype = DRefType.FLOAT_ARRAY
            value: Any = [0.0] * 8
            size = 8
            self.xp._dbg(f"Promoted '{name}' to dummy float array dataref")
        else:
            dtype = DRefType.FLOAT
            value = 0.0
            size = 1
            self.xp._dbg(f"Promoted '{name}' to dummy scalar dataref")

        ref = FakeDataRefInfo(
            path=name,
            xp_type=int(dtype),
            writable=True,
            is_array=is_array,
            size=size,
            dummy=True,
            value=value,
        )

        self._handles[name] = ref
        self._values[name] = value
        return ref

    def getDataRefInfo(self, handle: FakeDataRefInfo) -> FakeDataRefInfo:
        return handle

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _promote_if_dummy(self, ref: FakeDataRefInfo) -> FakeDataRefInfo:
        """
        If this is a dummy dataref, flip it to real and notify manager.
        Called on first read/write through the xp.* API.
        """
        if not ref.dummy:
            return ref

        # Flip dummy → real
        ref.dummy = False

        # Ensure value storage exists
        if ref.path not in self._values:
            self._values[ref.path] = ref.value

        # Notify promotion
        if self.xp._dataref_manager:
            self.xp._dataref_manager._notify_dataref_changed(ref)

        return ref

    def _resolve_value_ref(self, handle: FakeDataRefInfo | str) -> FakeDataRefInfo:
        if isinstance(handle, str):
            ref = self._handles.get(handle)
            if ref is None:
                ref = FakeDataRefInfo(
                    path=handle,
                    xp_type=1,
                    writable=True,
                    is_array=False,
                    size=1,
                    dummy=True,
                    value=0.0,
                )
                self._handles[handle] = ref
                self._values[handle] = 0.0
        else:
            ref = handle

        # Promotion happens on first access
        return self._promote_if_dummy(ref)

    # ------------------------------------------------------------------ #
    # Datai                                                              #
    # ------------------------------------------------------------------ #
    def getDatai(self, handle: FakeDataRefInfo | str) -> int:
        ref = self._resolve_value_ref(handle)
        return int(self._values.get(ref.path, ref.value))

    def setDatai(self, handle: FakeDataRefInfo | str, value: int) -> None:
        ref = self._resolve_value_ref(handle)
        v = int(value)
        self._values[ref.path] = v
        ref.value = v
        if self.xp._dataref_manager:
            self.xp._dataref_manager._notify_dataref_changed(ref)

    # ------------------------------------------------------------------ #
    # Dataf                                                              #
    # ------------------------------------------------------------------ #
    def getDataf(self, handle: FakeDataRefInfo | str) -> float:
        ref = self._resolve_value_ref(handle)
        return float(self._values.get(ref.path, ref.value))

    def setDataf(self, handle: FakeDataRefInfo | str, value: float) -> None:
        ref = self._resolve_value_ref(handle)
        v = float(value)
        self._values[ref.path] = v
        ref.value = v
        if self.xp._dataref_manager:
            self.xp._dataref_manager._notify_dataref_changed(ref)

    # ------------------------------------------------------------------ #
    # Datad                                                              #
    # ------------------------------------------------------------------ #
    def getDatad(self, handle: FakeDataRefInfo | str) -> float:
        return self.getDataf(handle)

    def setDatad(self, handle: FakeDataRefInfo | str, value: float) -> None:
        self.setDataf(handle, value)

    # ------------------------------------------------------------------ #
    # Datavf                                                             #
    # ------------------------------------------------------------------ #
    def getDatavf(
        self,
        handle: FakeDataRefInfo | str,
        out: List[float] | None,
        offset: int,
        count: int,
    ) -> int | None:
        ref = self._resolve_value_ref(handle)
        arr = self._values.get(ref.path, ref.value)
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = float(arr[offset + i])
        return None

    def setDatavf(
        self,
        handle: FakeDataRefInfo | str,
        values: Sequence[float],
        offset: int,
        count: int,
    ) -> None:
        ref = self._resolve_value_ref(handle)
        arr = self._values.setdefault(ref.path, ref.value or [])
        end = offset + count
        if end > len(arr):
            arr.extend([0.0] * (end - len(arr)))
        for i in range(count):
            arr[offset + i] = float(values[i])
        ref.value = arr
        if self.xp._dataref_manager:
            self.xp._dataref_manager._notify_dataref_changed(ref)

    # ------------------------------------------------------------------ #
    # Datvi                                                             #
    # ------------------------------------------------------------------ #
    def getDatvi(
        self,
        handle: FakeDataRefInfo | str,
        out: List[int] | None,
        offset: int,
        count: int,
    ) -> int | None:
        ref = self._resolve_value_ref(handle)
        arr = self._values.get(ref.path, ref.value)
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = int(arr[offset + i])
        return None

    def setDatvi(
        self,
        handle: FakeDataRefInfo | str,
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None:
        ref = self._resolve_value_ref(handle)
        arr = self._values.setdefault(ref.path, ref.value or [])
        end = offset + count
        if end > len(arr):
            arr.extend([0] * (end - len(arr)))
        for i in range(count):
            arr[offset + i] = int(values[i])
        ref.value = arr
        if self.xp._dataref_manager:
            self.xp._dataref_manager._notify_dataref_changed(ref)

    # ------------------------------------------------------------------ #
    # Datab                                                             #
    # ------------------------------------------------------------------ #
    def getDatab(
        self,
        handle: FakeDataRefInfo | str,
        out: bytearray | None,
        offset: int,
        count: int,
    ) -> int | None:
        ref = self._resolve_value_ref(handle)
        arr: bytearray = self._values.get(ref.path, ref.value)
        if out is None:
            return len(arr)
        for i in range(count):
            out[i] = arr[offset + i]
        return None

    def setDatab(
        self,
        handle: FakeDataRefInfo | str,
        values: Sequence[int],
        offset: int,
        count: int,
    ) -> None:
        ref = self._resolve_value_ref(handle)
        arr: bytearray = self._values.setdefault(ref.path, ref.value or bytearray())
        end = offset + count
        if end > len(arr):
            arr.extend([0] * (end - len(arr)))
        for i in range(count):
            arr[offset + i] = int(values[i]) & 0xFF
        ref.value = arr
        if self.xp._dataref_manager:
            self.xp._dataref_manager._notify_dataref_changed(ref)

    # ------------------------------------------------------------------ #
    # registerDataRef                                                   #
    # ------------------------------------------------------------------ #
    def registerDataRef(
        self,
        path: str,
        xpType: int,
        isArray: bool,
        writable: bool,
        defaultValue: Any,
    ) -> FakeDataRefInfo:
        if path in self._handles:
            return self._handles[path]

        ref = FakeDataRefInfo(
            path=path,
            xp_type=xpType,
            writable=writable,
            is_array=isArray,
            size=0,
            dummy=False,
            value=defaultValue,
        )

        self._handles[path] = ref
        self._values[path] = defaultValue
        self.xp._dbg(f"registerDataRef('{path}')")

        if self.xp._dataref_manager is not None:
            self.xp._dataref_manager._notify_dataref_changed(ref)

        return ref
