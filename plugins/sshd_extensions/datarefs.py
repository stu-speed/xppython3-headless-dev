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
    """
    Production-authentic description of a DataRef, plus plugin-side defaults.

    Fields are intentionally aligned with what XPPython3/X-Plane expose via
    XPLMDataRefInfo_t: type, writable, is_array (derived), size/count.
    """
    name: str
    type: int
    writable: bool

    required: bool = False
    default: Any = None

    handle: Optional[XPLMDataRef] = None
    is_dummy: bool = False

    is_array: bool = False
    count: int = 1

    @classmethod
    def from_info(
        cls,
        path: str,
        info: XPLMDataRefInfo_t,
        required: bool,
        default: Any,
        handle: Optional[XPLMDataRef] = None,
        is_dummy: bool = False,
    ) -> "DataRefSpec":
        """
        Build a spec from a real XPLMDataRefInfo_t.

        XPPython3/X-Plane provide:
          - info.type
          - info.writable
          - info.is_array (may be None)
          - info.size (may be None)
        """
        # size may be None in some environments; fall back to default shape
        size = getattr(info, "size", None)
        if size is None:
            if isinstance(default, (list, bytes, bytearray)):
                size = len(default)
            else:
                size = 1

        is_array = getattr(info, "is_array", None)
        if is_array is None:
            is_array = size > 1

        return cls(
            name=path,
            type=info.type,
            writable=info.writable,
            required=required,
            default=default,
            handle=handle,
            is_dummy=is_dummy,
            is_array=bool(is_array),
            count=int(size),
        )

    @classmethod
    def dummy(cls, path: str, *, required: bool, default: Any) -> "DataRefSpec":
        """
        Dummy spec used before X-Plane provides the real DataRef.
        Type/shape are inferred from defaults; later promoted via promote().
        """
        if isinstance(default, list):
            is_array = True
            count = len(default)
        elif isinstance(default, (bytes, bytearray)):
            is_array = True
            count = len(default)
        else:
            is_array = False
            count = 1

        return cls(
            name=path,
            type=int(DRefType.FLOAT),
            writable=False,
            required=required,
            default=default,
            handle=None,
            is_dummy=True,
            is_array=is_array,
            count=count,
        )

    def promote(self, handle: XPLMDataRef, info: XPLMDataRefInfo_t) -> None:
        """
        Promote a dummy spec to a real, bound DataRef using XPLMDataRefInfo_t.

        This is called once, from DataRefManager.ready(), when X-Plane (or
        FakeXP) finally provides the real DataRef.
        """
        self.handle = handle
        self.is_dummy = False

        # Mirror X-Plane/XPPython3 field names
        self.type = info.type
        self.writable = info.writable

        size = getattr(info, "size", None)
        if size is None:
            # Preserve existing count if X-Plane doesn't report size
            size = self.count or 1

        is_array = getattr(info, "is_array", None)
        if is_array is None:
            is_array = size > 1

        self.count = int(size)
        self.is_array = bool(is_array)

        # XP initializes DataRefs to zero; align defaults with that behavior
        if self.is_array:
            self.default = [0.0] * self.count
        else:
            self.default = 0.0


class DataRefManager:
    """
    Unified DataRef manager for production and simless.

    - In production (X-Plane), it binds to real DataRefs via xp.findDataRef()
      and xp.getDataRefInfo(), then uses xp.get*/set* for access.
    - In simless, FakeXP implements the same xp.* API and DataRefInfo fields,
      so this class runs unchanged.
    """

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
        self._all_real = True

    # ------------------------------------------------------------------
    # Startup resolution
    # ------------------------------------------------------------------

    def ready(self, counter: int) -> bool:
        """
        Bind all declared DataRefs once, using xp.findDataRef + xp.getDataRefInfo.

        Returns True only when:
          - all required DataRefs have real handles, or
          - timeout has elapsed and plugin has been disabled (for missing required).
        """
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
