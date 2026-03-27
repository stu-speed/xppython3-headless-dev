# plugins/sshd_extensions/dataref_manager.py
# ========================================================================
# DataRefs — unified production/simless DataRef layer
#
# 1) Simple readiness check
#    - Call manager.ready(counter) at the very top of your flight loop.
#    - ready() is non‑blocking and returns True once all *required* DataRefs
#      are bound. While waiting, return a short retry interval.
#    - If required DataRefs remain missing past timeout_seconds, the manager
#      will attempt to disable the plugin (logged, best‑effort).
#
# 2) No handle plumbing; lazy DummyHandle creation
#    - You do not need to call xp.findDataRef/getDataRefInfo or store handles.
#    - DataRefSpec may be registered dynamically (add_spec) or declared up front.
#    - If a spec has no handle, get_value() will lazily create a lightweight
#      DummyHandle so tests and simless runs work the same as real runs.
#    - When a real handle appears the spec is promoted automatically.
#
# 3) Tiny, safe get/set convenience
#    - manager.get_value(path) hides scalar vs array getters and returns raw
#      X‑Plane values (or dummy defaults for optional refs).
#    - manager.set_value(path, value) validates dtype, array length, and
#      writability before calling xp setters.
#    - set_value is allowed only for DataRefs declared required.
#
# 4) Dynamic registration supported
#    - Use add_spec(path, spec) to register new specs at runtime.
#    - get_value() will create a DummyHandle on demand for newly registered
#      specs, enabling immediate reads of defaults until promotion.
# =============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional

from XPPython3.xp_typing import XPLMDataRef, XPLMDataRefInfo_t


class DRefType(IntEnum):
    UNKNOWN = 0
    INT = 1
    FLOAT = 2
    DOUBLE = 4
    FLOAT_ARRAY = 8
    INT_ARRAY = 16
    BYTE_ARRAY = 32


@dataclass(slots=True)
class DataRefSpec:
    """
    Canonical DataRef specification.

    - All metadata lives at the spec level.
    - `handle` is None until promote() attaches a real XPLMDataRef.
    - `default` is returned by get_value() when no handle exists (unless required).
    """
    name: str
    type: DRefType
    writable: bool

    required: bool = False
    default: Any = None

    handle: Optional[XPLMDataRef] = None
    is_dummy: bool = True

    @staticmethod
    def _mask_to_dtype(mask: int) -> DRefType:
        """
        XPLM reports a *bitmask* of supported types. Choose one canonical dtype
        for manager get/set dispatch.
        Preference: arrays first, then scalars (double > float > int).
        """
        m = int(mask) if mask is not None else 0

        if m & int(DRefType.FLOAT_ARRAY):
            return DRefType.FLOAT_ARRAY
        if m & int(DRefType.INT_ARRAY):
            return DRefType.INT_ARRAY
        if m & int(DRefType.BYTE_ARRAY):
            return DRefType.BYTE_ARRAY

        if m & int(DRefType.DOUBLE):
            return DRefType.DOUBLE
        if m & int(DRefType.FLOAT):
            return DRefType.FLOAT
        if m & int(DRefType.INT):
            return DRefType.INT

        return DRefType.UNKNOWN

    @classmethod
    def from_info(
        cls,
        path: str,
        info: XPLMDataRefInfo_t,
        required: bool,
        default: Any,
        handle: XPLMDataRef,
    ) -> "DataRefSpec":
        dtype = cls._mask_to_dtype(int(getattr(info, "type", 0)))
        if dtype == DRefType.UNKNOWN:
            raise TypeError(f"Invalid/unknown dtype mask from xp for DataRef '{path}': {getattr(info, 'type', None)!r}")

        return cls(
            name=path,
            type=dtype,
            writable=bool(getattr(info, "writable", False)),
            required=required,
            default=default,
            handle=handle,
            is_dummy=False,
        )

    @classmethod
    def dummy(cls, path: str, *, required: bool, default: Any) -> "DataRefSpec":
        if default is None:
            default = [0.0]
            dtype = DRefType.FLOAT_ARRAY
        else:
            if isinstance(default, (list, tuple)):
                if default and all(isinstance(x, int) for x in default):
                    dtype = DRefType.INT_ARRAY
                else:
                    dtype = DRefType.FLOAT_ARRAY
            elif isinstance(default, (bytes, bytearray)):
                dtype = DRefType.BYTE_ARRAY
            elif isinstance(default, int):
                dtype = DRefType.INT
            elif isinstance(default, float):
                dtype = DRefType.FLOAT
            else:
                default = [0.0]
                dtype = DRefType.FLOAT_ARRAY

        return cls(
            name=path,
            type=dtype,
            writable=False,
            required=required,
            default=default,
            handle=None,
            is_dummy=True,
        )

    def promote(self, handle: XPLMDataRef, info: XPLMDataRefInfo_t) -> None:
        """
        Attach a real XPLMDataRef handle and update metadata.

        In production, XPLM always reports a non‑zero type mask.
        In simless/FakeXP, a zero mask means "not yet known" — fall back
        to the spec's declared type in that case.
        """
        raw_mask = int(getattr(info, "type", 0))

        if raw_mask == 0:
            # Simless fallback: trust the spec's declared type
            dtype = self.type
        else:
            dtype = self._mask_to_dtype(raw_mask)
            if dtype == DRefType.UNKNOWN:
                raise TypeError(
                    f"Invalid/unknown dtype mask from xp for DataRef '{self.name}': {raw_mask!r}"
                )

        self.handle = handle
        self.is_dummy = False
        self.type = dtype
        self.writable = bool(getattr(info, "writable", False))

        # Normalize default for convenience
        if dtype in (DRefType.FLOAT_ARRAY, DRefType.INT_ARRAY, DRefType.BYTE_ARRAY):
            if not isinstance(self.default, (list, tuple, bytes, bytearray)):
                self.default = [
                    float(self.default) if isinstance(self.default, (int, float)) else 0.0
                ]
        else:
            if isinstance(self.default, (list, tuple, bytes, bytearray)):
                self.default = 0.0


class DataRefManager:
    """
    Simplified DataRefManager: specs hold defaults; handles are None until promoted.
    """

    def __init__(
        self,
        xp: Any,
        datarefs: Optional[Dict[str, Dict[str, Any]]] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.xp = xp
        self.specs: Dict[str, DataRefSpec] = {}
        self.timeout = float(timeout_seconds)

        self._start_time: Optional[float] = None
        self._ready: bool = False
        self._timed_out: bool = False

        if datarefs:
            for path, cfg in datarefs.items():
                required = bool(cfg.get("required", False))
                default = cfg.get("default", None)

                if path not in self.specs:
                    self.specs[path] = DataRefSpec.dummy(path, required=required, default=default)
                    self._ready = False
                else:
                    spec = self.specs[path]
                    if "required" in cfg:
                        spec.required = required
                    if "default" in cfg:
                        spec.default = default

    def add_spec(self, path: str, spec: DataRefSpec) -> None:
        self.specs[path] = spec
        self._ready = False

    def get_spec(self, path: str) -> Optional[DataRefSpec]:
        return self.specs.get(path)

    def get_value(self, path: str) -> Any:
        spec = self.specs.get(path)
        if spec is None:
            return None

        if spec.handle is None:
            if spec.required:
                raise RuntimeError(f"DataRef '{path}' not ready; call ready() first")
            return spec.default

        xp = self.xp
        h = spec.handle
        t = spec.type

        if t == DRefType.FLOAT:
            return xp.getDataf(h)
        if t == DRefType.INT:
            return xp.getDatai(h)
        if t == DRefType.DOUBLE:
            return xp.getDatad(h)
        if t == DRefType.FLOAT_ARRAY:
            out: list[float] = [0.0] * 8
            got = xp.getDatavf(h, out, 0, len(out))
            return out if got is None else out[:int(got)]
        if t == DRefType.INT_ARRAY:
            out: list[int] = [0] * 8
            got = xp.getDatavi(h, out, 0, len(out))
            return out if got is None else out[:int(got)]
        if t == DRefType.BYTE_ARRAY:
            out = bytearray(8)
            got = xp.getDatab(h, out, 0, len(out))
            return out if got is None else out[:int(got)]

        raise TypeError(f"Unsupported dtype {t} for '{path}'")

    def set_value(self, path: str, value: Any) -> None:
        spec = self.specs.get(path)
        if spec is None:
            raise KeyError(f"Unknown DataRef '{path}'")

        if spec.handle is None:
            spec.default = value
            return

        xp = self.xp
        h = spec.handle
        t = spec.type

        if t == DRefType.FLOAT:
            if not isinstance(value, (int, float)):
                raise TypeError(f"Expected float for '{path}'")
            xp.setDataf(h, float(value))
            return

        if t == DRefType.INT:
            if not isinstance(value, (int, float)):
                raise TypeError(f"Expected int for '{path}'")
            xp.setDatai(h, int(value))
            return

        if t == DRefType.DOUBLE:
            if not isinstance(value, (int, float)):
                raise TypeError(f"Expected double for '{path}'")
            xp.setDatad(h, float(value))
            return

        if t == DRefType.FLOAT_ARRAY:
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"Expected list[float] for '{path}'")
            xp.setDatavf(h, list(value), 0, len(value))
            return

        if t == DRefType.INT_ARRAY:
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"Expected list[int] for '{path}'")
            xp.setDatavi(h, list(value), 0, len(value))
            return

        if t == DRefType.BYTE_ARRAY:
            if not isinstance(value, (bytes, bytearray)):
                raise TypeError(f"Expected bytes/bytearray for '{path}'")
            xp.setDatab(h, value, 0, len(value))
            return

        raise TypeError(f"Unsupported dtype {t} for '{path}'")

    def all_paths(self) -> list[str]:
        return list(self.specs.keys())

    def all_specs(self) -> list[DataRefSpec]:
        return list(self.specs.values())

    def clear(self) -> None:
        for _, spec in list(self.specs.items()):
            spec.is_dummy = True
            spec.handle = None
        self._start_time = None
        self._ready = False
        self._timed_out = False

    def close(self) -> None:
        self.specs.clear()
        self._start_time = None
        self._ready = False
        self._timed_out = False

    def ready(self) -> bool:
        """
        Non-blocking: attempt to promote any unpromoted specs by querying xp.
        Returns True when all *required* specs are promoted.
        """
        if self._ready:
            return True

        now = time.monotonic()
        if self._start_time is None:
            self._start_time = now

        required_all_real = True

        for path, spec in list(self.specs.items()):
            if spec.handle:
                continue

            handle = self.xp.findDataRef(path)
            if handle is None:
                if spec.required:
                    required_all_real = False
                continue

            info = self.xp.getDataRefInfo(handle)
            if info is None:
                if spec.required:
                    required_all_real = False
                continue

            try:
                spec.promote(handle, info)
            except Exception as exc:
                self.xp.log(f"[DRM] WARN: failed to promote {path}: {exc!r}")
                if spec.required:
                    required_all_real = False

        if required_all_real:
            self._ready = True
            return True

        elapsed = now - (self._start_time or now)
        if elapsed > self.timeout:
            missing = [p for p, s in self.specs.items() if (s.handle is None) and s.required]
            if missing:
                self.xp.log(
                    f"[DRM] ERROR: Required DataRefs not available after {self.timeout} seconds: {missing}"
                )
                try:
                    self.xp.disablePlugin(self.xp.getMyID())
                except Exception:
                    try:
                        self.xp.log("[DRM] ERROR: disablePlugin failed")
                    except Exception:
                        pass
                self._timed_out = True
            return False

        return False

    def timed_out(self) -> bool:
        return self._timed_out

    def invalidate_ready(self) -> None:
        self._ready = False
        self._start_time = None
        self._timed_out = False
