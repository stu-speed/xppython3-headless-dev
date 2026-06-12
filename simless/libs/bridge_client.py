# ===========================================================================
# XP Bridge Protocol — headless DataRef synchronization layer (indexed, tuple-based)
#
# PROTOCOL (JSON on the wire, list-based, index-addressed)
# --------------------------------------------------------
#   ["add",   [path, path, ...]]                 client → server: request tracking of DataRefs
#   ["reset"]                                    client → server: explicit full reset request
#   ["meta",  [idx, name, type, writable, array_size]]
#                                                server → client: normalized metadata
#   ["update",[ [idx, value], [idx, value], ...]]
#                                                server → client: changed DataRef values
#   ["error", "message"]                         server → client: error message
#   ["ping"]                                     server → client: keepalive / heartbeat
#   ["pong"]                                     client → server: keepalive response
#
# ROLE
#   The bridge is a thin transport layer between real X‑Plane and the
#   simless runner. It must not contain business logic, inference, or
#   validation. It only forwards metadata and values.
#
# CORE INVARIANTS
#   - Uses the Public API as much as possible.
#   - Never mutates X‑Plane SDK objects (XPLMDataRefInfo_t is read‑only).
#   - Never infers semantics beyond what X‑Plane exposes.
#   - Never performs validation; DataRefSpec owns all validation logic.
#   - Never performs type coercion; values are forwarded as returned by XP.
#   - Single client only: if either side goes down, full reset.
#   - Server owns heartbeat; client only responds with PONG.
#   - Only one send path per side: all outbound messages use _send().
#   - Heartbeat activity is based only on outbound sends and new connections.
#   - Wire format is JSON arrays; Python side uses NamedTuples for all messages.
# ===========================================================================

from __future__ import annotations

import errno
import os
import socket
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING, TextIO

import select

from XPPython3 import xp
from simless.libs.fake_xp_types import FakeDataRef
from sshd_extensions.bridge_protocol import BRIDGE_HOST, BRIDGE_PORT, BridgeMsg, BridgeMsgType, HEARTBEAT_TIMEOUT, \
    MT_Add, MT_Pong, MT_Reset

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP

RECONNECT_INTERVAL: float = float(os.getenv("XPBRIDGE_RECONNECT_INTERVAL", "30.0"))
CONNECT_TIMEOUT: float = float(os.getenv("XPBRIDGE_CONNECT_TIMEOUT", "5.0"))

# Cross-platform "in progress" codes
in_progress = (
    0,
    errno.EINPROGRESS,
    errno.EWOULDBLOCK,
    10035,  # Windows WSAEWOULDBLOCK
)


def describe_socket_error(err: int) -> str:
    """
    Return a human-readable, platform-independent description
    of a socket error code.
    """

    # Cross-platform mapping
    mapping = {
        0: "Success",
        errno.EINPROGRESS: "Operation in progress (non-blocking connect)",
        errno.EWOULDBLOCK: "Operation would block (non-blocking connect)",
        errno.EALREADY: "Connection already in progress",
        errno.ECONNREFUSED: "Connection refused (no server listening)",
        errno.ETIMEDOUT: "Connection timed out",
        errno.EHOSTUNREACH: "Host unreachable",
        errno.ENETUNREACH: "Network unreachable",

        # Windows-only codes (safe to include everywhere)
        10035: "Operation would block (Windows WSAEWOULDBLOCK)",
        10036: "Operation now in progress",
        10037: "Operation already in progress",
        10060: "Connection timed out",
        10061: "Connection refused (no server listening)",
        10064: "Host is down",
        10065: "No route to host",
    }

    return mapping.get(err, f"Unknown socket error {err}")


# =======================================================================
# User-friendly client-side event model
# =======================================================================

class BridgeDataType(str, Enum):
    """Enumeration of high-level bridge event types.

    These values represent the user-facing, path-based event categories
    produced by XPBridgeClient.poll_data(). They abstract away the
    low-level wire-format message types.
    """
    META = "meta"
    UPDATE = "update"
    ERROR = "error"


@dataclass(slots=True)
class BridgeData:
    """User-friendly, path-based representation of bridge events.

    This dataclass is produced by XPBridgeClient.poll_data() and is
    consumed by the simless runner and DataRefManager. It hides all
    wire-format details (idx, NamedTuples, raw JSON) and exposes only
    the information needed for deterministic DataRef synchronization.

    Attributes:
        type (BridgeDataType):
            The high-level event type (META, UPDATE, or ERROR).

        path (Optional[str]):
            The DataRef path associated with the event. META and UPDATE
            events always include a path; ERROR events do not.

        dtype (Optional[int]):
            The X-Plane data type (int-encoded) for META events. None
            for UPDATE and ERROR events.

        writable (Optional[bool]):
            Whether the DataRef is writable. Only present for META
            events.

        array_size (Optional[int]):
            Size of the DataRef array for array types. Only present for
            META events; zero or None for scalar types.

        value (Any):
            The updated DataRef value for UPDATE events. None for META
            and ERROR events.

        text (Optional[str]):
            Error message text for ERROR events. None for META and
            UPDATE events.
    """
    type: BridgeDataType
    path: Optional[str]  # None for errors
    dtype: Optional[int]  # Only for META
    writable: Optional[bool]  # Only for META
    array_size: Optional[int]  # Only for META
    value: Any  # Only for UPDATE
    text: Optional[str]  # Only for ERROR


# =======================================================================
# XPBridgeClient — simless runner side
# =======================================================================
class XPBridgeClient:
    """
    Lightweight TCP client for the XP DataRef bridge.

    The client uses the protocol-level constants BRIDGE_HOST and
    BRIDGE_PORT as its authoritative connection target. FakeXP may
    override these attributes after construction for local development.
    """

    def __init__(
            self,
            fake_xp: FakeXP,
            host: Optional[str] = None,
            port: Optional[int] = None,
    ) -> None:
        self.fake_xp = fake_xp

        self.host: str = host or BRIDGE_HOST
        self.port: int = port or BRIDGE_PORT

        self._enabled = False

        # TCP connection state
        self.sock: Optional[socket.socket] = None
        self.file: Optional[TextIO] = None

        # Heartbeat: client enforces timeout based on inbound activity
        self._last_activity: float = 0.0

        # Client-side idx → path mapping (for user-friendly BridgeData events)
        self._idx_to_path: Dict[int, str] = {}

        self._conn_status: str = "Disabled"
        self._session_initialized = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def conn_status(self) -> str:
        if not self.enabled:
            text = "Bridge: DISABLED"
        else:
            state = "DISCONNECTED"
            if self.sock and self.file:
                state = "CONNECTED"
            elif self.sock and self.file is None:
                state = "PENDING"
            text = f"Bridge: {state} - {self._conn_status}"
        return text

    @property
    def menu_label(self) -> str:
        return "Disable Dataref Bridge" if self.enabled else "Enable Dataref Bridge"

    def set_enabled(self, enable: bool) -> None:
        if enable:
            xp.log(f"[Bridge] Enable connection")
            self._enabled = True
            self.fake_xp.dataref_manager.attach_handle_callback(self._on_dataref_handle_created)
            self._last_activity = time.time() - 100  # connect right away
        else:
            xp.log(f"[Bridge] Disable connection")
            self._enabled = False
            self.fake_xp.dataref_manager.detach_handle_callback()
            self.disconnect()
        self.fake_xp.simless_runner.dataref_viewer.viewer_widget.bridge_status = self.conn_status

    def set_conn_status(self, status: str) -> None:
        self._conn_status = status
        xp.log(f"[Bridge] {self._conn_status}")
        self.fake_xp.simless_runner.dataref_viewer.viewer_widget.bridge_status = self.conn_status

    def connect(self) -> None:
        self.disconnect()

        self.set_conn_status(f"Connecting to {self.host}:{self.port}")

        self._last_activity = time.time()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)

        # Start non-blocking connect
        err = sock.connect_ex((self.host, self.port))
        if err not in in_progress:
            raise ConnectionError(describe_socket_error(err))

        # Store socket; connection not finished yet
        self.sock = sock
        self.file = None
        self._session_initialized = False

    def disconnect(self) -> None:
        if self.file:
            try:
                self.file.close()
            except Exception:
                pass
            self.file = None

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    # ------------------------------------------------------------------
    # Unified send path — ONLY place that calls sock.sendall()
    # ------------------------------------------------------------------
    def _send_batch(self, msgs: List[BridgeMsg]) -> None:
        if not self.sock:
            raise RuntimeError("Client not connected")
        if not msgs:
            return

        data = BridgeMsg.encode_batch(msgs)
        self.sock.sendall(data)
        self._last_activity = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add(self, paths: List[str]) -> None:
        """Request tracking of one or more DataRefs."""
        self._send_batch([BridgeMsg(BridgeMsgType.ADD, MT_Add(paths=paths))])

    def reset(self) -> None:
        """Explicit full reset request; both sides should rebuild state."""
        self._send_batch([BridgeMsg(BridgeMsgType.RESET, MT_Reset())])

    def get_path_for_idx(self, idx: int) -> Optional[str]:
        return self._idx_to_path.get(idx)

    def ready_for_processing(self) -> bool:
        if not self.enabled:
            return False

        now = time.time()

        # --------------------------------------------------------------
        # 1. If disconnected, retry connection every RECONNECT_INTERVAL
        # --------------------------------------------------------------
        if self.sock is None and self.file is None:
            if now - self._last_activity < RECONNECT_INTERVAL:
                return False
            try:
                self.connect()
            except Exception as exc:
                self.set_conn_status(str(exc))
                return False

        # If connecting (sock exists but file not created yet)
        if self.sock is not None and self.file is None:
            _, wlist, xlist = select.select([], [self.sock], [self.sock], 0)

            if wlist or xlist:
                self._last_activity = now

                # Check final connect status
                err = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err != 0:
                    # Connect failed
                    self.disconnect()
                    self.set_conn_status(describe_socket_error(err))
                    return False

                # Connect succeeded
                self.file = self.sock.makefile("r", encoding="utf-8", newline="\n")
                return True

            if now - self._last_activity > CONNECT_TIMEOUT:
                self.disconnect()
                self.set_conn_status(f"Connect timeout after {CONNECT_TIMEOUT} seconds")

            return False

        # --------------------------------------------------------------
        # 2. Connected: heartbeat timeout → disconnect + raise
        # --------------------------------------------------------------
        if now - self._last_activity > HEARTBEAT_TIMEOUT:
            self.disconnect()
            self.set_conn_status(f"Heartbeat timeout after {HEARTBEAT_TIMEOUT} seconds")
            return False

        return True

    # ------------------------------------------------------------------
    # Poll for inbound messages (wire format)
    # ------------------------------------------------------------------
    def poll_wire(self) -> List[BridgeMsg]:
        """
        Poll for inbound bridge messages.

        Returns:
            List[BridgeMsg]: Zero or more decoded bridge messages.

        Raises:
            ConnectionResetError: If the server closes the connection or the
                heartbeat timeout is exceeded while connected.
            Exception: Any protocol or socket error encountered while connected.
        """
        assert self.sock is not None
        assert self.file is not None

        rlist, _, _ = select.select([self.sock], [], [], 0)
        if not rlist:
            return []

        line = self.file.readline()
        if line == "":
            self.disconnect()
            self.set_conn_status("Server closed connection")
            raise ConnectionResetError(self.conn_status)

        self._last_activity = time.time()

        stripped = line.strip()
        if not stripped:
            return []

        # --------------------------------------------------------------
        # 5. Decode batch (raise on protocol errors)
        # --------------------------------------------------------------
        msgs = BridgeMsg.decode_batch(stripped)

        # --------------------------------------------------------------
        # 6. Maintain idx → path mapping
        # --------------------------------------------------------------
        for m in msgs:
            if m.type == BridgeMsgType.META:
                v = m.value
                self._idx_to_path[v.idx] = v.name

        # --------------------------------------------------------------
        # 7. Respond to PING (raise if send fails)
        # --------------------------------------------------------------
        if any(m.type == BridgeMsgType.PING for m in msgs):
            self._send_batch([BridgeMsg(BridgeMsgType.PONG, MT_Pong())])

        return msgs

    # ------------------------------------------------------------------
    # Poll for inbound messages (user-friendly, path-based)
    # ------------------------------------------------------------------
    def poll_data(self) -> List[BridgeData]:
        """
        Poll for inbound messages and return a user-friendly, path-based
        representation suitable for the simless runner and DataRefManager.
        """
        wire_msgs = self.poll_wire()
        out: List[BridgeData] = []

        for m in wire_msgs:
            t = m.type
            v = m.value

            if t == BridgeMsgType.META:
                path = self._idx_to_path.get(v.idx)
                out.append(
                    BridgeData(
                        type=BridgeDataType.META,
                        path=path,
                        dtype=v.type,
                        writable=v.writable,
                        array_size=v.array_size,
                        value=None,
                        text=None,
                    )
                )

            elif t == BridgeMsgType.UPDATE:
                for entry in v.entries:
                    path = self._idx_to_path.get(entry.idx)
                    out.append(
                        BridgeData(
                            type=BridgeDataType.UPDATE,
                            path=path,
                            dtype=None,
                            writable=None,
                            array_size=None,
                            value=entry.value,
                            text=None,
                        )
                    )

            elif t == BridgeMsgType.ERROR:
                out.append(
                    BridgeData(
                        type=BridgeDataType.ERROR,
                        path=None,
                        dtype=None,
                        writable=None,
                        array_size=None,
                        value=None,
                        text=v.text,
                    )
                )

        return out

    def _on_dataref_handle_created(self, ref: FakeDataRef) -> None:
        """Called synchronously when FakeXPDataRef creates a handle."""
        if not self.ready_for_processing():
            return

        try:
            self.add([ref.path])
        except Exception as exc:
            try:
                self.fake_xp.log(f"[Bridge] add dataref failed for {ref.path}: {exc}")
            except Exception:
                pass

    def _register_all_datarefs_with_bridge(self) -> None:
        """Register all known DataRef paths with the bridge.

        Called once on initial bridge connection and again on reconnect.
        """

        self._idx_to_path.clear()
        all_handle_paths = self.fake_xp.dataref_manager.all_handle_paths()
        if not all_handle_paths:
            return
        self.fake_xp.log(f"[Bridge] Sync {len(all_handle_paths)} known DataRef paths with bridge.")
        try:
            self.add(all_handle_paths)
        except Exception as exc:
            self.fake_xp.log(f"[Bridge] add datarefs failed- {exc}")

    # ----------------------------------------------------------------------
    # Bridge management
    # ----------------------------------------------------------------------
    # NOTE:
    # is_dummy means both type and value are provisional.
    # It flips to False only on the first provider‑originated UPDATE,
    # never on META.
    def manage_bridged_datarefs(self) -> None:
        """Poll bridge events and update DataRefManager state.

        Connection management is handled entirely by XPBridgeClient.poll().
        This method only:
          • polls for inbound events,
          • applies META/UPDATE changes,
          • logs bridge errors.
        """

        try:
            events: List[BridgeData] = self.poll_data()
        except ConnectionResetError:
            return

        if not self._session_initialized:
            self._register_all_datarefs_with_bridge()
            self._session_initialized = True
            self.set_conn_status(f"Bridge sync active")

        for ev in events:
            if not ev.path:
                continue
            if ev.type is BridgeDataType.META:
                ref = self.fake_xp.dataref_manager.get_handle(ev.path)
                if not ref or not ev.dtype:
                    continue

                # Promote TYPE authority only
                self.fake_xp.dataref_manager.promote_type(
                    ref=ref,
                    dtype=ev.dtype,
                    writable=bool(ev.writable),
                )

            elif ev.type is BridgeDataType.UPDATE:
                ref = self.fake_xp.dataref_manager.get_handle(ev.path)
                assert ref is not None, f"Unknown handle: {ev.path}"
                value = ev.value

                is_array = isinstance(value, (list, tuple, bytearray))
                size = len(value) if is_array else 1

                # Promote shape if needed (first time or shape change)
                if (
                        not ref.shape_known
                        or ref.is_array != is_array
                        or ref.size != size
                ):
                    self.fake_xp.dataref_manager.promote_shape_from_value(
                        ref=ref,
                        value=value,
                    )
                else:
                    ref.value = value

            elif ev.type is BridgeDataType.ERROR:
                self.fake_xp.log(f"[Bridge] ERROR: {ev.text}")
