# simless/libs/fake_xp_dataref.py
# =======================================================================
# FakeXP DataRef subsystem — xp_typing-backed implementation
#
# CORE INVARIANTS
#   • Public API signatures MUST MATCH real X‑Plane / XPPython3.
#   • FakeDataRef is the single authoritative value store.
#
# PRINCIPLES
#   • Single handle type: FakeDataRef returned by findDataRef.
#   • Dummy-first: findDataRef creates a dummy (is_dummy=True) so plugins get
#     a handle immediately; runner/bridge promotes it later.
#   • In-place promotion: promote_handle flips is_dummy -> False and updates
#     metadata on the same object.
#   • Single global lock: one RLock protects _handles and all handle state.
#   • Subsystem-composed: FakeXP binds only declared public API names.
#
# ARRAY SEMANTICS
#   • Dummy handles: array writes replace the backing buffer (elastic placeholder).
#   • Real handles: array writes update in-place and enforce bounds (production parity).
#   • Array getters: `offset` is the destination buffer offset (XPLM semantics).
# =======================================================================

from __future__ import annotations

from typing import Any, Dict, Optional, Callable
import threading
import copy

from simless.libs.fake_xp_dataref_types import FakeDataRef
from sshd_extensions.dataref_manager import DRefType
from simless.libs.fake_xp_dataref_api import FakeXPDataRefAPI


class FakeXPDataRef(FakeXPDataRefAPI):
    """
    FakeXP DataRef subsystem using a single global lock.

    IMPORTANT:
      • Do NOT implement __init__ in this subsystem class.
      • FakeXP composes subsystems and calls `_init_dataref()` during initialization.
      • This subsystem explicitly declares the FakeXP API endpoints it exposes.
        FakeXP must bind ONLY these names onto the xp facade.
    """

    # ------------------------------------------------------------------
    # Public FakeXP API surface
    # ------------------------------------------------------------------
    public_api_names = [
        # Lookup + metadata
        "findDataRef",
        "getDataRefInfo",
        "getDataRefTypes",
        "canWriteDataRef",
        "isDataRefGood",

        # Scalar accessors
        "getDatai", "setDatai",
        "getDataf", "setDataf",
        "getDatad", "setDatad",

        # Array accessors
        "getDatavf", "setDatavf",
        "getDatavi", "setDatavi",
        "getDatab", "setDatab",

        # String helpers
        "getDatas", "setDatas",

        # simless
        "all_handle_paths", "all_handles", "get_handle",
        "promote_type", "promote_shape_from_value",
        "update_dataref",
        "attach_handle_callback", "detach_handle_callback",
    ]

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def _init_dataref(self) -> None:
        """
        Initialize internal state for the DataRef subsystem.
        This method is called by FakeXP; do not call from subsystem constructors.
        """
        self._handles: Dict[str, FakeDataRef] = {}
        # accessor metadata for registered accessors (name -> metadata)
        self._accessors: Dict[str, Dict[str, Any]] = {}
        self._handle_callback = None
        # single global lock protecting _handles and all handle state
        self._handles_lock = threading.RLock()
        # simple owner id counter for registered accessors
        self._next_owner_id = 1

    # -------------------------
    # Callback management
    # -------------------------
    def attach_handle_callback(self, cb: Optional[Callable[[FakeDataRef], None]]) -> None:
        """Register a single synchronous callback invoked when a handle is created. Passing None clears it."""
        with self._handles_lock:
            self._handle_callback = cb

    def detach_handle_callback(self) -> None:
        with self._handles_lock:
            self._handle_callback = None

    # -------------------------
    # Dummy update and promotion helpers
    # -------------------------

    def get_handle(self, name: str) -> Optional[FakeDataRef]:
        with self._handles_lock:
            return self._handles.get(name)

    def all_handle_paths(self) -> list[str]:
        """Return a snapshot of all known DataRef handle paths."""
        with self._handles_lock:
            return list(self._handles.keys())

    def all_handles(self) -> list[FakeDataRef]:
        """Return a snapshot of all known DataRef handles."""
        with self._handles_lock:
            return list(self._handles.values())

    def promote_type(
        self,
        ref: FakeDataRef,
        *,
        dtype: DRefType,
        writable: bool,
    ) -> None:
        """
        Promote type authority for an existing handle.

        This method is called when authoritative metadata (META) is received.
        It establishes numeric type and writability.

        Semantics:
          • Promotion is in-place; the FakeDataRef object is preserved.
          • Existing dummy values are preserved if compatible with the new type.
          • Incompatible dummy values are replaced with a default value.
          • Shape (scalar vs array, size) is NOT inferred or modified.
          • Idempotent: safe to call multiple times.

        Raises:
          • TypeError if ref is invalid
        """
        if ref is None:
            raise TypeError("invalid dataRef")

        with self._handles_lock:
            ref.type = dtype
            ref.writable = bool(writable)

            # Validate or coerce existing value
            try:
                if isinstance(ref.value, (list, bytearray)):
                    # Do not reshape here — only validate element type
                    if dtype == DRefType.FLOAT_ARRAY:
                        ref.value = [float(x) for x in ref.value]
                    elif dtype == DRefType.INT_ARRAY:
                        ref.value = [int(x) for x in ref.value]
                    elif dtype == DRefType.BYTE_ARRAY:
                        ref.value = bytearray(ref.value)
                    else:
                        # Scalar type cannot accept array value
                        ref.value = self._default_value_for(dtype, 1)
                else:
                    # Scalar value
                    if dtype in (DRefType.FLOAT, DRefType.DOUBLE):
                        ref.value = float(ref.value)
                    elif dtype == DRefType.INT:
                        ref.value = int(ref.value)
                    else:
                        ref.value = self._default_value_for(dtype, 1)
            except (TypeError, ValueError):
                # Replace incompatible dummy value
                ref.value = self._default_value_for(dtype, 1)

            ref.type_known = True

    def promote_shape_from_value(
        self,
        ref: FakeDataRef,
        value: Any,
    ) -> None:
        """
        Promote shape authority for an existing handle using an authoritative value.

        This method is called on the first real provider UPDATE.
        The provided value is authoritative for both shape and storage.

        Semantics:
          • Promotion is in-place; the FakeDataRef object is preserved.
          • Shape (scalar vs array) and size are inferred from the value.
          • Existing dummy values are discarded unconditionally.
          • Storage is allocated to exactly match the value shape.
          • Idempotent: safe to call multiple times.

        Raises:
          • TypeError if ref is invalid
        """
        if ref is None:
            raise TypeError("invalid dataRef")

        with self._handles_lock:
            if ref.shape_known:
                return

            if isinstance(value, (list, tuple, bytearray)):
                ref.is_array = True
                ref.size = len(value)

                if ref.type == DRefType.BYTE_ARRAY:
                    ref.value = bytearray(value)
                elif ref.type == DRefType.FLOAT_ARRAY:
                    ref.value = [float(x) for x in value]
                elif ref.type == DRefType.INT_ARRAY:
                    ref.value = [int(x) for x in value]
                else:
                    raise TypeError("array value incompatible with scalar type")
            else:
                ref.is_array = False
                ref.size = 1

                if ref.type in (DRefType.FLOAT, DRefType.DOUBLE):
                    ref.value = float(value)
                elif ref.type == DRefType.INT:
                    ref.value = int(value)
                else:
                    ref.value = self._default_value_for(ref.type, 1)

            ref.shape_known = True

    # -------------------------
    # DataRef update helper
    # -------------------------
    def update_dataref(
        self,
        ref: FakeDataRef,
        dtype: Optional[DRefType] = None,
        size: Optional[int] = None,
        writable: Optional[bool] = None,
        value: Optional[Any] = None,
    ) -> FakeDataRef:
        """
        Update an existing FakeDataRef in-place (dummy or live).

        Semantics:
          • Handle identity is preserved.
          • is_dummy is NOT modified.
          • dtype/size/writable updated if provided.
          • Arrays replace the backing buffer atomically.
          • Scalars are coerced.
          • No promotion logic is applied.

        Raises:
          • ValueError on invalid size
          • TypeError if ref is invalid
        """
        with self._handles_lock:
            if ref is None:
                raise TypeError("invalid dataRef")

            if size is not None:
                if size <= 0:
                    raise ValueError("size must be > 0")
                ref.size = int(size)

            if dtype is not None:
                ref.type = dtype

            if writable is not None:
                ref.writable = bool(writable)

            if value is None:
                return ref

            # Array types: replace backing buffer
            if ref.type == DRefType.FLOAT_ARRAY:
                buf = [float(x) for x in value]
                buf = (buf + [0.0] * ref.size)[: ref.size]
                ref.value = buf
                return ref

            if ref.type == DRefType.INT_ARRAY:
                buf = [int(x) for x in value]
                buf = (buf + [0] * ref.size)[: ref.size]
                ref.value = buf
                return ref

            if ref.type == DRefType.BYTE_ARRAY:
                buf = bytearray(value)
                buf = (buf + b"\x00" * ref.size)[: ref.size]
                ref.value = buf
                return ref

            # Scalar types
            ref.size = 1
            if ref.type in (DRefType.FLOAT, DRefType.DOUBLE):
                ref.value = float(value)
            elif ref.type == DRefType.INT:
                ref.value = int(value)
            else:
                ref.value = copy.deepcopy(value)

            return ref
