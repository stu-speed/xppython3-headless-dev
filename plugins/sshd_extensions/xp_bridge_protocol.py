# ===========================================================================
# XP Bridge Protocol — headless DataRef synchronization layer
#
# PROTOCOL
# --------
#   ADD(path)    — client → server: request tracking of a DataRef
#   RESET        — client → server: explicit full reset request
#   META(meta)   — server → client: normalized metadata:
#                  { name, type, writable, array_size }
#   UPDATE(dict) — server → client: changed DataRef values
#   ERROR(str)   — server → client: error message
#   PING         — server → client: keepalive / heartbeat
#   PONG         — client → server: keepalive response
#
# ROLE
#   The bridge is a thin transport layer between real X‑Plane and the
#   simless runner. It must not contain business logic, inference, or
#   validation. It only forwards metadata and values.
#
# CORE INVARIANTS
#   - Will use the Public API as much as possible
#   - Never mutate X‑Plane SDK objects (XPLMDataRefInfo_t is read‑only).
#   - Never infer semantics beyond what X‑Plane exposes.
#   - Never perform validation; DataRefSpec owns all validation logic.
#   - Never perform type coercion; values are forwarded as returned by XP.
#   - Single client only: if either side goes down, full reset.
#   - Server owns heartbeat; client only responds with PONG.
#   - Only one send path per side: all outbound messages use _send().
#   - Heartbeat activity is based only on outbound sends and new connections.
# ===========================================================================

from __future__ import annotations

import copy
import json
import select
import socket
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, TextIO, Union

from XPPython3.xp_typing import XPLMFlightLoopID

from sshd_extensions.xp_interface import XPInterface
from sshd_extensions.datarefs import DataRefSpec, DataRefManager, DRefType


# ===========================================================================
# Global epsilon for all DataRefs
# ===========================================================================
EPSILON = 0.001
HEARTBEAT_TIMEOUT = 10.0


def _changed(a: Any, b: Any) -> bool:
    """
    Return True if values differ by more than EPSILON.
    Works for scalars and arrays.
    """
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) > EPSILON

    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return True
        return any(abs(x - y) > EPSILON for x, y in zip(a, b))

    return a != b


# ===========================================================================
# Metadata dataclass (normalized)
# ===========================================================================
@dataclass(slots=True)
class BridgeMeta:
    name: str
    type: int
    writable: bool
    array_size: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "writable": self.writable,
            "array_size": self.array_size,
        }

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> "BridgeMeta":
        return BridgeMeta(
            name=obj["name"],
            type=obj["type"],
            writable=obj["writable"],
            array_size=obj["array_size"],
        )


# ===========================================================================
# Unified wire message
# ===========================================================================
class MsgType(Enum):
    ADD = "add"
    RESET = "reset"
    UPDATE = "update"
    ERROR = "error"
    META = "meta"
    PING = "ping"
    PONG = "pong"


ValueType = Union[str, dict, BridgeMeta]


@dataclass(slots=True)
class BridgeMessage:
    type: MsgType
    value: ValueType

    def to_dict(self) -> Dict[str, Any]:
        v = self.value
        if isinstance(v, BridgeMeta):
            return {"type": self.type.value, "value": v.to_dict()}
        return {"type": self.type.value, "value": v}

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> "BridgeMessage":
        msg_type = MsgType(obj["type"])
        value = obj.get("value", "")
        if msg_type is MsgType.META and isinstance(value, dict):
            value = BridgeMeta.from_dict(value)
        return BridgeMessage(type=msg_type, value=value)


# ===========================================================================
# XPBridgeServer — X‑Plane side
# ===========================================================================
class XPBridgeServer:
    def __init__(
        self,
        xp_interface: XPInterface,
        host: str = "0.0.0.0",
        port: int = 49099,
        rate: float = 0.05
    ) -> None:
        self.xp = xp_interface
        self.host = host
        self.port = port
        self.rate = rate

        self.server_sock: Optional[socket.socket] = None
        self.client_sock: Optional[socket.socket] = None
        self.client_file: Optional[TextIO] = None

        # Full specs: path → DataRefSpec
        self.specs: Dict[str, DataRefSpec] = {}

        # Manager starts empty
        self.manager = DataRefManager(self.xp, timeout_seconds=0.0)

        self.last_sent: Dict[str, Any] = {}

        # Heartbeat: server-driven, based only on outbound sends + new connection
        self._last_activity: float = time.time()

        self._open_server()

    # ----------------------------------------------------------------------
    # TCP server lifecycle
    # ----------------------------------------------------------------------
    def _open_server(self) -> None:
        self._close_server()

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(1)
        srv.setblocking(False)

        self.server_sock = srv
        self.xp.log(f"[Bridge] listening on {self.host}:{self.port}")

    def _close_server(self) -> None:
        if self.server_sock:
            self.xp.log("[Bridge] closing server socket")
            try:
                self.server_sock.close()
            except Exception as exc:
                self.xp.log(f"[Bridge] error closing server socket: {exc!r}")
            self.server_sock = None

    def _close_client(self) -> None:
        if self.client_sock or self.client_file:
            self.xp.log("[Bridge] closing client connection")

        if self.client_file:
            try:
                self.client_file.close()
            except Exception as exc:
                self.xp.log(f"[Bridge] error closing client_file: {exc!r}")
            self.client_file = None

        if self.client_sock:
            try:
                self.client_sock.close()
            except Exception as exc:
                self.xp.log(f"[Bridge] error closing client_sock: {exc!r}")
            self.client_sock = None

        self._reset_session_full()

    # ----------------------------------------------------------------------
    # Session lifecycle
    # ----------------------------------------------------------------------
    def _reset_session_full(self) -> None:
        """
        Full reset: used whenever the TCP client is gone or explicitly requests RESET.
        Clears all specs, manager state, last_sent.
        """
        self.xp.log("[Bridge] FULL RESET of session state")
        self.specs = {}
        self.manager.clear()
        self.last_sent = {}
        # Activity is only advanced on new connection or outbound send
        self._last_activity = time.time()

    # ----------------------------------------------------------------------
    # Unified send path — ONLY place that calls client_sock.sendall()
    # ----------------------------------------------------------------------
    def _send(self, msg: BridgeMessage) -> None:
        if not self.client_sock:
            return

        data = json.dumps(msg.to_dict()).encode("utf-8") + b"\n"
        try:
            self.client_sock.sendall(data)
            self._last_activity = time.time()
        except Exception as exc:
            self.xp.log(f"[Bridge] send failed: {exc!r}")
            self._close_client()

    def _send_error(self, text: str) -> None:
        self._send(BridgeMessage(type=MsgType.ERROR, value=text))

    # ----------------------------------------------------------------------
    # Flightloop callback
    # ----------------------------------------------------------------------
    def flightloop_cb(
        self,
        elapsed_since_last_call: float,
        elapsed_time_since_last_flightloop: float,
        counter: int,
        refcon: XPLMFlightLoopID,
    ) -> float:

        now = time.time()

        # Accept new client only if none is connected
        if self.client_sock is None and self.server_sock is not None:
            try:
                client, addr = self.server_sock.accept()
            except BlockingIOError:
                client = None
                addr = None
            except Exception as exc:
                self.xp.log(f"[Bridge] accept() failed: {exc!r}")
                client = None
                addr = None

            if client:
                client.setblocking(False)
                self.client_sock = client
                self.client_file = client.makefile("r", encoding="utf-8", newline="\n")
                self._reset_session_full()
                self.xp.log(f"[Bridge] client connected from {addr}")
                self._last_activity = now

        if not self.client_sock or not self.client_file:
            return -1.0

        sock = self.client_sock

        # Non-blocking read
        rlist, _, _ = select.select([sock], [], [], 0.0)
        if rlist:
            try:
                line = self.client_file.readline()
            except Exception as exc:
                self.xp.log(f"[Bridge] read failed: {exc!r}")
                self._close_client()
                return -1.0

            if line == "":
                self.xp.log("[Bridge] client disconnected (EOF)")
                self._close_client()
                return -1.0

            stripped = line.strip()
            if stripped:
                self._process_line(stripped)

        # Tick + send updates or heartbeat
        msg = self._tick(counter)
        if msg is not None:
            self._send(msg)
        else:
            # No UPDATE pending: send heartbeat if idle for timeout/2
            if now - self._last_activity > (HEARTBEAT_TIMEOUT / 2.0):
                self._send(BridgeMessage(type=MsgType.PING, value=""))

        # Heartbeat timeout: no outbound activity for full timeout
        if now - self._last_activity > HEARTBEAT_TIMEOUT:
            self.xp.log("[Bridge] heartbeat timeout — closing client and full reset")
            self._close_client()
            return -1.0

        return self.rate

    # ----------------------------------------------------------------------
    # Inbound message handling
    # ----------------------------------------------------------------------
    def _process_line(self, line: str) -> None:
        try:
            msg = BridgeMessage.from_dict(json.loads(line))
        except Exception as exc:
            self.xp.log(f"[Bridge] invalid JSON from client: {exc!r} line={line!r}")
            self._send_error("invalid json")
            return

        if msg.type is MsgType.ADD:
            self.xp.log(f"[Bridge] ADD {msg.value!r}")
            self._apply_add(str(msg.value))

        elif msg.type is MsgType.RESET:
            self.xp.log("[Bridge] RESET from client — full reset")
            self._reset_session_full()

        elif msg.type is MsgType.PONG:
            # Client acknowledged our PING; inbound messages do not affect _last_activity
            pass

        # META / UPDATE / ERROR / PING are server-originated only

    # ----------------------------------------------------------------------
    # Apply ADD — build real DataRefSpec, send normalized metadata
    # ----------------------------------------------------------------------
    def _apply_add(self, path: str) -> None:
        handle = self.xp.findDataRef(path)
        if handle is None:
            self.xp.log(f"[Bridge] ADD failed: DataRef not found: {path}")
            self._send_error(f"DataRef not found: {path}")
            return

        info = self.xp.getDataRefInfo(handle)
        if info is None:
            self.xp.log(f"[Bridge] ADD failed: DataRef info unavailable: handle={handle}")
            self._send_error(f"DataRef info unavailable: handle={handle}")
            return

        # Compute array_size using correct X‑Plane getter pattern
        t = info.type
        if t == int(DRefType.FLOAT_ARRAY):
            array_size = self.xp.getDatavf(handle, None, 0, 0)
        elif t == int(DRefType.INT_ARRAY):
            array_size = self.xp.getDatavi(handle, None, 0, 0)
        elif t == int(DRefType.BYTE_ARRAY):
            array_size = self.xp.getDatab(handle, None, 0, 0)
        else:
            array_size = 0  # scalar

        try:
            spec = DataRefSpec.from_info(
                path=path,
                info=info,
                required=False,
                default=None,
                handle=handle,
                is_dummy=False,
                array_size=array_size,
            )

            self.specs[path] = spec
            self.manager.add_spec(path, spec)

        except Exception as exc:
            self.xp.log(f"[Bridge] Failed to add spec for {path}: {exc!r}")
            self._send_error(f"Failed to add spec for {path}: {exc!r}")
            return

        # Send META = normalized metadata
        meta = BridgeMeta(
            name=path,
            type=info.type,
            writable=info.writable,
            array_size=array_size,
        )
        self.xp.log(
            f"[Bridge] META for {path}: type={info.type} writable={info.writable} array_size={array_size}"
        )
        self._send(BridgeMessage(type=MsgType.META, value=meta))

    # ----------------------------------------------------------------------
    # Outbound update computation
    # ----------------------------------------------------------------------
    def _tick(self, counter: int) -> Optional[BridgeMessage]:
        if not self.manager.ready(counter):
            return None

        payload: Dict[str, Any] = {}
        changed = False

        for path in self.manager.all_paths():
            value = self.manager.get_value(path)
            if value is None:
                continue

            last = self.last_sent.get(path)
            if last is None or _changed(value, last):
                changed = True
                payload[path] = value
                self.last_sent[path] = copy.deepcopy(value)

        if changed and payload:
            return BridgeMessage(type=MsgType.UPDATE, value=payload)

        return None


# ===========================================================================
# XPBridgeClient — simless runner side
# ===========================================================================
class XPBridgeClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

        self.sock: Optional[socket.socket] = None
        self.file: Optional[TextIO] = None

        # Heartbeat: client enforces timeout based on outbound sends + connect
        self._last_activity: float = time.time()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    def connect(self) -> None:
        self.disconnect()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect((self.host, self.port))

        self.sock = sock
        self.file = sock.makefile("r", encoding="utf-8", newline="\n")
        self._last_activity = time.time()

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

        self._last_activity = time.time()

    # ------------------------------------------------------------------
    # Unified send path — ONLY place that calls sock.sendall()
    # ------------------------------------------------------------------
    def _send(self, msg: BridgeMessage) -> None:
        if not self.sock:
            raise RuntimeError("Client not connected")

        data = json.dumps(msg.to_dict()).encode("utf-8") + b"\n"
        self.sock.sendall(data)
        self._last_activity = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add(self, path: str) -> None:
        self._send(BridgeMessage(type=MsgType.ADD, value=path))

    def reset(self) -> None:
        # Explicit full reset request; both sides should rebuild state.
        self._send(BridgeMessage(type=MsgType.RESET, value=""))

    # ------------------------------------------------------------------
    # Poll for inbound messages
    # ------------------------------------------------------------------

    def poll(self) -> Optional[BridgeMessage]:
        if self.file is None:
            raise ConnectionError("poll() with no connection")

        now = time.time()

        # Heartbeat timeout: no inbound activity for full timeout
        if now - self._last_activity > HEARTBEAT_TIMEOUT:
            self.disconnect()
            raise ConnectionResetError(f"heartbeat timeout after {HEARTBEAT_TIMEOUT} seconds")

        # Use select to check readability
        rlist, _, _ = select.select([self.sock], [], [], 0)

        if not rlist:
            # No data available; no activity
            return None

        # Socket is readable → safe to read
        line = self.file.readline()

        if line == "":
            # EOF → server closed connection
            self.disconnect()
            raise ConnectionResetError("server closed connection")

        # Inbound activity → refresh timer
        self._last_activity = now

        stripped = line.strip()
        if not stripped:
            return None

        msg = BridgeMessage.from_dict(json.loads(stripped))

        if msg.type is MsgType.PING:
            self._send(BridgeMessage(type=MsgType.PONG, value=""))
            return msg

        return msg

