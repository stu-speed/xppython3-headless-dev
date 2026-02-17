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

import copy
import json
import select
import socket
import time
from collections import namedtuple
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO, Tuple, Union

from XPPython3.xp_typing import XPLMFlightLoopID

from sshd_extensions.xp_interface import XPInterface
from sshd_extensions.datarefs import DataRefSpec, DataRefManager, DRefType


EPSILON = 0.001
HEARTBEAT_TIMEOUT = 10.0
BRIDGE_PORT = 49099


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


# =======================================================================
# Bridge message model (NamedTuples + enum + unified class)
# =======================================================================

class BridgeMsgType(str, Enum):
    ADD = "add"
    RESET = "reset"
    META = "meta"
    UPDATE = "update"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


Meta = namedtuple("Meta", "idx name type writable array_size")
UpdateEntry = namedtuple("UpdateEntry", "idx value")
Update = namedtuple("Update", "entries")          # entries: List[UpdateEntry]
Add = namedtuple("Add", "paths")                  # paths: List[str]
Reset = namedtuple("Reset", "")                   # no fields
Ping = namedtuple("Ping", "")                     # no fields
Pong = namedtuple("Pong", "")                     # no fields
ErrorMsg = namedtuple("ErrorMsg", "text")         # text: str

BridgeMsgValue = Union[Meta, Update, Add, Reset, Ping, Pong, ErrorMsg]


class BridgeMsg:
    """
    A single message in the bridge protocol.
    Owns all encoding/decoding logic and type → payload mapping.
    """

    _registry: Dict[BridgeMsgType, Tuple[type, Callable, Callable]] = {}

    def __init__(self, type: BridgeMsgType, value: BridgeMsgValue):
        self.type = type
        self.value = value

    # ------------------------------------------------------------------
    # Registration decorator
    # ------------------------------------------------------------------
    @classmethod
    def register(cls, msg_type: BridgeMsgType):
        def decorator(payload_cls):
            enc = getattr(payload_cls, "_encode")
            dec = getattr(payload_cls, "_decode")
            cls._registry[msg_type] = (payload_cls, enc, dec)
            return payload_cls
        return decorator

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------
    def to_json_obj(self) -> Any:
        payload_cls, enc, _ = self._registry[self.type]
        raw = enc(self.value)
        if raw is None:
            return [self.type.value]
        return [self.type.value, raw]

    def to_json_line(self) -> bytes:
        return json.dumps(self.to_json_obj()).encode("utf-8") + b"\n"

    @staticmethod
    def encode_batch(msgs: List["BridgeMsg"]) -> bytes:
        return json.dumps([m.to_json_obj() for m in msgs]).encode("utf-8") + b"\n"

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------
    @classmethod
    def from_json_obj(cls, raw: Sequence[Any]) -> "BridgeMsg":
        if not raw:
            raise ValueError("empty message")
        t = BridgeMsgType(raw[0])
        payload_cls, _, dec = cls._registry[t]
        if len(raw) == 1:
            value = dec(None)
        else:
            value = dec(raw[1])
        return BridgeMsg(t, value)

    @classmethod
    def decode_batch(cls, line: str) -> List["BridgeMsg"]:
        raw = json.loads(line)
        if not isinstance(raw, list):
            raise ValueError("batch must be a JSON array")
        return [cls.from_json_obj(m) for m in raw]

    def to_dict(self) -> dict:
        """
        Convert this BridgeMsg into a clean Python dict with field names.
        Recursively converts NamedTuples inside lists/dicts.
        """

        def convert(obj):
            # NamedTuple → dict
            if hasattr(obj, "_asdict"):
                return {k: convert(v) for k, v in obj._asdict().items()}

            # list → list
            if isinstance(obj, list):
                return [convert(x) for x in obj]

            # dict → dict
            if isinstance(obj, dict):
                return {k: convert(v) for k, v in obj.items()}

            # scalar
            return obj

        return {
            "type": self.type.value,
            "value": convert(self.value),
        }


# -----------------------------------------------------------------------
# Payload registration
# -----------------------------------------------------------------------

@BridgeMsg.register(BridgeMsgType.META)
class _Meta(Meta):
    @staticmethod
    def _encode(v: Meta):
        return list(v)

    @staticmethod
    def _decode(raw):
        return Meta(*raw)


@BridgeMsg.register(BridgeMsgType.UPDATE)
class _Update(Update):
    @staticmethod
    def _encode(v: Update):
        return [[e.idx, e.value] for e in v.entries]

    @staticmethod
    def _decode(raw):
        return Update([UpdateEntry(idx=e[0], value=e[1]) for e in raw])


@BridgeMsg.register(BridgeMsgType.ADD)
class _Add(Add):
    @staticmethod
    def _encode(v: Add):
        return list(v.paths)

    @staticmethod
    def _decode(raw):
        return Add(paths=list(raw))


@BridgeMsg.register(BridgeMsgType.RESET)
class _Reset(Reset):
    @staticmethod
    def _encode(v: Reset):
        return None

    @staticmethod
    def _decode(raw):
        return Reset()


@BridgeMsg.register(BridgeMsgType.PING)
class _Ping(Ping):
    @staticmethod
    def _encode(v: Ping):
        return None

    @staticmethod
    def _decode(raw):
        return Ping()


@BridgeMsg.register(BridgeMsgType.PONG)
class _Pong(Pong):
    @staticmethod
    def _encode(v: Pong):
        return None

    @staticmethod
    def _decode(raw):
        return Pong()


@BridgeMsg.register(BridgeMsgType.ERROR)
class _Error(ErrorMsg):
    @staticmethod
    def _encode(v: ErrorMsg):
        return v.text

    @staticmethod
    def _decode(raw):
        return ErrorMsg(text=raw)


# =======================================================================
# XPBridgeServer — X‑Plane side
# =======================================================================
class XPBridgeServer:
    def __init__(
        self,
        xp_interface: XPInterface,
        host: str = "0.0.0.0",
        port: int = 49099,
        rate: float = 0.05,
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

        # Last sent values keyed by idx
        self.last_sent: Dict[int, Any] = {}

        # Path → idx and idx → path mappings
        self._path_to_idx: Dict[str, int] = {}
        self._idx_to_path: Dict[int, str] = {}
        self._next_idx: int = 1

        # Heartbeat: server-driven, based only on outbound sends + new connection
        self._last_activity: float = time.time()

        self._open_server()

    # ------------------------------------------------------------------
    # TCP server lifecycle
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def _reset_session_full(self) -> None:
        """
        Full reset: used whenever the TCP client is gone or explicitly requests RESET.
        Clears all specs, manager state, last_sent, and index mappings.
        """
        self.xp.log("[Bridge] FULL RESET of session state")
        self.specs = {}
        self.manager.clear()
        self.last_sent = {}
        self._path_to_idx = {}
        self._idx_to_path = {}
        self._next_idx = 1
        self._last_activity = time.time()

    # ------------------------------------------------------------------
    # Unified send path — ONLY place that calls client_sock.sendall()
    # ------------------------------------------------------------------
    def _send_batch(self, msgs: List[BridgeMsg]) -> None:
        if not self.client_sock or not msgs:
            return

        data = BridgeMsg.encode_batch(msgs)
        try:
            self.client_sock.sendall(data)
            self._last_activity = time.time()
        except Exception as exc:
            self.xp.log(f"[Bridge] send failed: {exc!r}")
            self._close_client()

    def _send_error(self, text: str) -> None:
        self._send_batch([BridgeMsg(BridgeMsgType.ERROR, ErrorMsg(text=text))])

    # ------------------------------------------------------------------
    # Flightloop callback
    # ------------------------------------------------------------------
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
                try:
                    msgs = BridgeMsg.decode_batch(stripped)
                except Exception as exc:
                    self.xp.log(f"[Bridge] invalid JSON batch from client: {exc!r} line={stripped!r}")
                    self._send_error("invalid json")
                else:
                    for msg in msgs:
                        self._process_msg(msg)

        # Tick + send updates or heartbeat
        outbound: List[BridgeMsg] = []
        update_msg = self._tick(counter)
        if update_msg is not None:
            outbound.append(update_msg)
        else:
            if now - self._last_activity > (HEARTBEAT_TIMEOUT / 2.0):
                outbound.append(BridgeMsg(BridgeMsgType.PING, Ping()))

        if outbound:
            self._send_batch(outbound)

        # Heartbeat timeout only applies when a client is connected
        if self.client_sock is not None and (now - self._last_activity > HEARTBEAT_TIMEOUT):
            self.xp.log("[Bridge] heartbeat timeout — closing client and full reset")
            self._close_client()
            return -1.0

        return self.rate

    # ------------------------------------------------------------------
    # Inbound message handling
    # ------------------------------------------------------------------
    def _process_msg(self, msg: BridgeMsg) -> None:
        t = msg.type
        v = msg.value

        if t == BridgeMsgType.ADD:
            self.xp.log(f"[Bridge] ADD {v.paths!r}")
            for path in v.paths:
                self._apply_add(path)

        elif t == BridgeMsgType.RESET:
            self.xp.log("[Bridge] RESET from client — full reset")
            self._reset_session_full()

        elif t == BridgeMsgType.PONG:
            # Client acknowledged our PING; inbound messages do not affect _last_activity
            pass

        # META / UPDATE / ERROR / PING are server-originated only

    # ------------------------------------------------------------------
    # Apply ADD — build real DataRefSpec, send normalized metadata
    # ------------------------------------------------------------------
    def _next_index_for_path(self, path: str) -> int:
        existing = self._path_to_idx.get(path)
        if existing is not None:
            return existing
        idx = self._next_idx
        self._next_idx += 1
        self._path_to_idx[path] = idx
        self._idx_to_path[idx] = path
        return idx

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

        idx = self._next_index_for_path(path)

        meta = Meta(
            idx=idx,
            name=path,
            type=info.type,
            writable=info.writable,
            array_size=array_size,
        )
        self.xp.log(
            f"[Bridge] META for {path}: idx={idx} type={info.type} "
            f"writable={info.writable} array_size={array_size}"
        )
        self._send_batch([BridgeMsg(BridgeMsgType.META, meta)])

    # ------------------------------------------------------------------
    # Outbound update computation
    # ------------------------------------------------------------------
    def _tick(self, counter: int) -> Optional[BridgeMsg]:
        if not self.manager.ready(counter):
            return None

        entries: List[UpdateEntry] = []
        changed = False

        for path in self.manager.all_paths():
            idx = self._path_to_idx.get(path)
            if idx is None:
                continue

            value = self.manager.get_value(path)
            if value is None:
                continue

            last = self.last_sent.get(idx)
            if last is None or _changed(value, last):
                changed = True
                entries.append(UpdateEntry(idx=idx, value=copy.deepcopy(value)))
                self.last_sent[idx] = copy.deepcopy(value)

        if changed and entries:
            return BridgeMsg(BridgeMsgType.UPDATE, Update(entries=entries))

        return None


# =======================================================================
# XPBridgeClient — simless runner side
# =======================================================================
class XPBridgeClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

        self.sock: Optional[socket.socket] = None
        self.file: Optional[TextIO] = None

        # Heartbeat: client enforces timeout based on inbound activity + connect
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
    def _send_batch(self, msgs: List[BridgeMsg]) -> None:
        if not self.sock:
            raise RuntimeError("Client not connected")

        data = BridgeMsg.encode_batch(msgs)
        self.sock.sendall(data)
        self._last_activity = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add(self, paths: List[str]) -> None:
        """
        Request tracking of one or more DataRefs.
        """
        self._send_batch([BridgeMsg(BridgeMsgType.ADD, Add(paths=list(paths)))])

    def reset(self) -> None:
        """
        Explicit full reset request; both sides should rebuild state.
        """
        self._send_batch([BridgeMsg(BridgeMsgType.RESET, Reset())])

    # ------------------------------------------------------------------
    # Poll for inbound messages
    # ------------------------------------------------------------------
    def poll(self) -> List[BridgeMsg]:
        """
        Poll for inbound messages.
        Returns a list of BridgeMsg. May be empty if no data available.
        Raises ConnectionResetError on heartbeat timeout or server close.
        """
        if self.file is None or self.sock is None:
            raise ConnectionError("poll() with no connection")

        now = time.time()

        if now - self._last_activity > HEARTBEAT_TIMEOUT:
            self.disconnect()
            raise ConnectionResetError(
                f"heartbeat timeout after {HEARTBEAT_TIMEOUT} seconds"
            )

        rlist, _, _ = select.select([self.sock], [], [], 0)
        if not rlist:
            return []

        line = self.file.readline()

        if line == "":
            self.disconnect()
            raise ConnectionResetError("server closed connection")

        self._last_activity = now

        stripped = line.strip()
        if not stripped:
            return []

        msgs = BridgeMsg.decode_batch(stripped)

        pong_needed = any(m.type == BridgeMsgType.PING for m in msgs)
        if pong_needed:
            self._send_batch([BridgeMsg(BridgeMsgType.PONG, Pong())])

        return msgs
