# ===========================================================================
# DataRefs — unified production/simless DataRef layer
# ===========================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional, Iterable

from XPPython3.xp_typing import XPLMDataRef, XPLMDataRefInfo_t
from sshd_extensions.xp_interface import XPInterface


class DRefType(IntEnum):
    INT         = 1
    FLOAT       = 2
    DOUBLE      = 4
    FLOAT_ARRAY = 8
    INT_ARRAY   = 16
    BYTE_ARRAY  = 32


@dataclass(slots=True)
class DataRefSpec:
    name: str
    type: int
    writable: bool
    owner: int

    required: bool = False
    default: Any = None

    handle: Optional[XPLMDataRef] = None
    is_dummy: bool = False

    dtype: int = 0
    is_array: bool = False
    count: int = 1

    @classmethod
    def from_info(
        cls,
        info: XPLMDataRefInfo_t,
        required: bool,
        default: Any,
        handle: Optional[XPLMDataRef] = None,
        is_dummy: bool = False,
    ) -> "DataRefSpec":
        return cls(
            name=info.name,
            type=info.xp_type,
            writable=info.writable,
            owner=info.owner,
            required=required,
            default=default,
            handle=handle,
            is_dummy=is_dummy,
            dtype=info.xp_type,
            is_array=info.size > 1,
            count=info.size,
        )

    @classmethod
    def dummy(cls, path: str, *, required: bool, default: Any) -> "DataRefSpec":
        return cls(
            name=path,
            type=int(DRefType.FLOAT),
            writable=False,
            owner=0,
            required=required,
            default=default,
            handle=None,
            is_dummy=True,
            dtype=int(DRefType.FLOAT),
            is_array=isinstance(default, list),
            count=len(default) if isinstance(default, list) else 1,
        )

    def promote(self, handle, info) -> None:
        self.handle = handle
        self.is_dummy = False

        self.type = info.xp_type
        self.dtype = info.xp_type
        self.is_array = info.size > 1
        self.count = info.size
        self.writable = info.writable

        # XP initializes DataRefs to zero
        if self.is_array:
            self.default = [0.0] * info.size
        else:
            self.default = 0.0


class DataRefManager:

    def __init__(
        self,
        xp: XPInterface,
        datarefs: Optional[Dict[Any, Dict[str, Any]]] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.xp = xp
        self.timeout = timeout_seconds
        self._start_counter: Optional[int] = None

        self.specs: Dict[str, DataRefSpec] = {}
        self._all_real: bool = True

        # Bind into FakeXP so FakeXPDataRef can see plugin defaults
        if hasattr(self.xp, "bind_dataref_manager"):
            self.xp.bind_dataref_manager(self)

        if datarefs:
            self._all_real = False
            for key, cfg in datarefs.items():
                path = key
                required = cfg.get("required", False)
                default = cfg.get("default", None)
                self.specs[path] = DataRefSpec.dummy(
                    path,
                    required=required,
                    default=default,
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_spec(self, path: str, spec: DataRefSpec) -> None:
        self.specs[path] = spec

    def get_value(self, path: str) -> Any:
        spec = self.specs.get(path)
        if spec is None:
            return None

        if spec.is_dummy or spec.handle is None:
            return spec.default

        xp = self.xp
        h = spec.handle
        t = spec.type

        if t == int(DRefType.FLOAT):
            return xp.getDataf(h)
        if t == int(DRefType.INT):
            return xp.getDatai(h)
        if t == int(DRefType.DOUBLE):
            return xp.getDatad(h)
        if t == int(DRefType.FLOAT_ARRAY):
            size = xp.getDatavf(h, None, 0, 0)
            out = [0.0] * size
            xp.getDatavf(h, out, 0, size)
            return out
        if t == int(DRefType.INT_ARRAY):
            size = xp.getDatvi(h, None, 0, 0)
            out = [0] * size
            xp.getDatvi(h, out, 0, size)
            return out
        if t == int(DRefType.BYTE_ARRAY):
            size = xp.getDatab(h, None, 0, 0)
            out = bytearray(size)
            xp.getDatab(h, out, 0, size)
            return out

        raise TypeError(f"Unsupported dtype {t}")

    def all_paths(self) -> Iterable[str]:
        return self.specs.keys()

    def clear(self) -> None:
        self.specs.clear()
        self._start_counter = None

    # ------------------------------------------------------------------
    # Startup resolution
    # ------------------------------------------------------------------

    def ready(self, counter: int) -> bool:
        if self._all_real:
            return True

        if self._start_counter is None:
            self._start_counter = counter
            return False

        all_real = True

        for path, spec in list(self.specs.items()):
            if not spec.is_dummy:
                continue

            handle = self.xp.findDataRef(path)
            if handle is None:
                all_real = False
                continue

            info = self.xp.getDataRefInfo(handle)
            spec.promote(handle, info)

        if all_real:
            self._all_real = True
            return True

        # Timeout
        elapsed = counter - self._start_counter
        if elapsed > self.timeout:
            missing = [
                p for p, s in self.specs.items()
                if s.is_dummy and s.required
            ]
            if missing:
                self.xp.log(
                    f"[DRM] ERROR: Required DataRefs not available after "
                    f"{self.timeout} seconds: {missing}"
                )
                self.xp.disablePlugin(self.xp.getMyID())
            return False

        return False
