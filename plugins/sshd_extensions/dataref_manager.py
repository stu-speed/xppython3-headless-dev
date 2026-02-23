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
# plugins/sshd_extensions/dataref_manager.py
# ========================================================================
# DataRefs — simplified DataRef layer (no DummyHandle)
#
# - DummyHandle removed: DataRefSpec holds defaults and top-level metadata.
# - spec.handle is None until a real XPLMDataRef is attached via promote().
# - get_value returns spec.default when no handle exists (unless required).
# - set_value allowed only for specs declared required and only after promotion.
# - No array_size bookkeeping or strict array-length validation.
# ========================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional, Iterable, Callable

import time

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

    # Real handle (XPLMDataRef) or None until promoted
    handle: Optional[XPLMDataRef] = None
    is_dummy: bool = True

    @classmethod
    def from_info(
        cls,
        path: str,
        info: XPLMDataRefInfo_t,
        required: bool,
        default: Any,
        handle: XPLMDataRef,
    ) -> "DataRefSpec":
        try:
            dtype = DRefType(int(info.type))
        except Exception as exc:
            raise TypeError(f"Invalid dtype from xp for DataRef '{path}': {info.type!r}") from exc

        spec = cls(
            name=path,
            type=dtype,
            writable=bool(info.writable),
            required=required,
            default=default,
            handle=handle,
            is_dummy=False,
        )
        return spec

    @classmethod
    def dummy(cls, path: str, *, required: bool, default: Any) -> "DataRefSpec":
        # If default is None, choose a convenient default: single-element float array.
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
                # fallback to single-element float array
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

        No array-size parameter; we do not perform strict array-length validation.
        """
        try:
            dtype = DRefType(int(info.type))
        except Exception as exc:
            raise TypeError(f"Invalid dtype from xp for DataRef '{self.name}': {info.type!r}") from exc

        self.handle = handle
        self.is_dummy = False
        self.type = dtype
        self.writable = bool(info.writable)

        # Align default for convenience: arrays -> single-element float array, scalars -> 0.0
        if dtype in (DRefType.FLOAT_ARRAY, DRefType.INT_ARRAY, DRefType.BYTE_ARRAY):
            # If default was previously scalar, convert to a small list for consistency
            if not isinstance(self.default, (list, tuple, bytes, bytearray)):
                self.default = [float(self.default) if isinstance(self.default, (int, float)) else 0.0]
        else:
            # scalar
            if isinstance(self.default, (list, tuple, bytes, bytearray)):
                # collapse to scalar 0.0 for convenience
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
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.xp = xp
        self.specs: Dict[str, DataRefSpec] = {}
        self.timeout = float(timeout_seconds)
        self.clock = clock or time.monotonic

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

    # Public API
    def add_spec(self, path: str, spec: DataRefSpec) -> None:
        self.specs[path] = spec
        self._ready = False

    def get_spec(self, path: str) -> Optional[DataRefSpec]:
        return self.specs.get(path)

    # Value retrieval
    def get_value(self, path: str) -> Any:
        spec = self.specs.get(path)
        if spec is None:
            return None

        # If no handle yet, return default for optional refs; required refs must call ready()
        if spec.handle is None:
            if spec.required:
                raise RuntimeError(f"DataRef '{path}' not ready; call ready() first")
            return spec.default

        # Real handle path: call xp getters
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
            if got is None:
                return out
            return out[:int(got)]
        if t == DRefType.INT_ARRAY:
            out: list[int] = [0] * 8
            got = xp.getDatavi(h, out, 0, len(out))
            if got is None:
                return out
            return out[:int(got)]
        if t == DRefType.BYTE_ARRAY:
            out = bytearray(8)
            got = xp.getDatab(h, out, 0, len(out))
            if got is None:
                return out
            return out[:int(got)]

        raise TypeError(f"Unsupported dtype {t}")

    # Value write
    def set_value(self, path: str, value: Any) -> None:
        spec = self.specs.get(path)
        if spec is None:
            raise KeyError(f"Unknown DataRef '{path}'")

        # Just update default if no handle
        if spec.handle is None:
            spec.default = value
            return

        xp = self.xp
        h = spec.handle
        t = spec.type

        # Scalars
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

        # Arrays: forward lists/bytes to xp as-is (no strict length validation)
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

        raise TypeError(f"Unsupported dtype {t}")

    # Utility
    def all_paths(self) -> Iterable[str]:
        return self.specs.keys()

    def list_specs(self) -> list[DataRefSpec]:
        return list(self.specs.values())

    def clear(self) -> None:
        """
        Reset all specs to unpromoted state; defaults remain on the spec.
        """
        for path, spec in list(self.specs.items()):
            spec.is_dummy = True
            spec.handle = None
        self._start_time = None
        self._ready = False
        self._timed_out = False

    def close(self) -> None:
        """
        Cleanup references; no xp side effects.
        """
        self.specs.clear()
        self._start_time = None
        self._ready = False
        self._timed_out = False

    # Startup resolution (non-blocking)
    def ready(self) -> bool:
        """
        Non-blocking: attempt to promote any unpromoted specs by querying xp.
        Returns True when all required specs are promoted.
        """
        if self._ready:
            return True

        now = self.clock()
        if self._start_time is None:
            self._start_time = now

        all_real = True

        for path, spec in list(self.specs.items()):
            if spec.handle:
                continue

            handle = self.xp.findDataRef(path)
            if handle is None:
                all_real = False
                continue

            info = self.xp.getDataRefInfo(handle)
            if info is None:
                all_real = False
                continue

            try:
                # Validate dtype convertible
                _ = DRefType(int(info.type))
            except Exception:
                self.xp.log(f"[DRM] WARN: invalid dtype for {path}: {info.type!r}")
                all_real = False
                continue

            try:
                spec.promote(handle, info)
            except Exception as exc:
                self.xp.log(f"[DRM] WARN: failed to promote {path}: {exc!r}")
                all_real = False

        if all_real:
            self._ready = True
            return True

        elapsed = now - (self._start_time or now)
        if elapsed > self.timeout:
            missing = [
                p for p, s in self.specs.items()
                if (s.handle is None) and s.required
            ]
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
        """
        External callers may call this when xp disconnects or handles become invalid.
        """
        self._ready = False
        self._start_time = None
        self._timed_out = False
