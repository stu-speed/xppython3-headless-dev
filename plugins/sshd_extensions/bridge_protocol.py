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
import os
import select
import socket
import time
from collections import namedtuple
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO, Tuple, Union

from XPPython3.xp_typing import XPLMFlightLoopID

from sshd_extensions.xp_interface import XPInterface
from sshd_extensions.dataref_manager import DataRefSpec, DataRefManager, DRefType

EPSILON: float = float(os.getenv("XPBRIDGE_EPSILON", "0.001"))
RECONNECT_INTERVAL: float = float(os.getenv("XPBRIDGE_RECONNECT_INTERVAL", "10.0"))
HEARTBEAT_TIMEOUT: float = float(os.getenv("XPBRIDGE_HEARTBEAT_TIMEOUT", "10.0"))

BRIDGE_HOST: str = os.getenv("XPBRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT: int = int(os.getenv("XPBRIDGE_PORT", "49099"))


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
Update = namedtuple("Update", "entries")  # entries: List[UpdateEntry]
Add = namedtuple("Add", "paths")  # paths: List[str]
Reset = namedtuple("Reset", "")  # no fields
Ping = namedtuple("Ping", "")  # no fields
Pong = namedtuple("Pong", "")  # no fields
ErrorMsg = namedtuple("ErrorMsg", "text")  # text: str

BridgeMsgValue = Union[Meta, Update, Add, Reset, Ping, Pong, ErrorMsg]


class BridgeMsg:
    """A single wire‑format message in the bridge protocol.

    BridgeMsg owns all encoding and decoding logic for the tuple‑based,
    index‑addressed JSON protocol. Each message consists of a message
    type (BridgeMsgType) and a payload object whose structure is defined
    by the registered payload class.

    Attributes:
        type (BridgeMsgType):
            The message type discriminator (e.g., META, UPDATE, ADD).

        value (BridgeMsgValue):
            The payload object associated with this message type. The
            concrete type depends on the registry entry for `type`.
    """

    # Registry: msg_type → (payload_cls, encode_fn, decode_fn)
    _registry: Dict[BridgeMsgType, Tuple[type, Callable, Callable]] = {}

    def __init__(self, type: BridgeMsgType, value: BridgeMsgValue) -> None:
        """Construct a BridgeMsg.

        Args:
            type (BridgeMsgType):
                The message type discriminator.

            value (BridgeMsgValue):
                The payload object for this message. Must match the
                payload class registered for `type`.
        """
        self.type: BridgeMsgType = type
        self.value: BridgeMsgValue = value

    # ------------------------------------------------------------------
    # Registration decorator
    # ------------------------------------------------------------------
    @classmethod
    def register(cls, msg_type: BridgeMsgType):
        """Decorator used by payload classes to register themselves.

        Args:
            msg_type (BridgeMsgType):
                The message type this payload class handles.

        Returns:
            Callable: A decorator that registers the payload class and
            its encode/decode functions.
        """

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
        """Convert this message into a JSON‑serializable list.

        Returns:
            Any: A JSON‑serializable Python object representing the
            message in wire format.
        """
        payload_cls, enc, _ = self._registry[self.type]
        raw = enc(self.value)
        if raw is None:
            return [self.type.value]
        return [self.type.value, raw]

    def to_json_line(self) -> bytes:
        """Encode this message as a JSON line suitable for socket I/O.

        Returns:
            bytes: UTF‑8 encoded JSON line ending with a newline.
        """
        return json.dumps(self.to_json_obj()).encode("utf-8") + b"\n"

    @staticmethod
    def encode_batch(msgs: List["BridgeMsg"]) -> bytes:
        """Encode a batch of messages as a single JSON line.

        Args:
            msgs (List[BridgeMsg]):
                Messages to encode.

        Returns:
            bytes: UTF‑8 encoded JSON array with newline terminator.
        """
        return json.dumps([m.to_json_obj() for m in msgs]).encode("utf-8") + b"\n"

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------
    @classmethod
    def from_json_obj(cls, raw: Sequence[Any]) -> "BridgeMsg":
        """Decode a single wire‑format JSON object into a BridgeMsg.

        Args:
            raw (Sequence[Any]):
                The raw JSON array representing a single message.

        Returns:
            BridgeMsg: The decoded message instance.

        Raises:
            ValueError: If the message is empty or malformed.
        """
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
        """Decode a JSON line containing a batch of messages.

        Args:
            line (str):
                A JSON array encoded as a single line.

        Returns:
            List[BridgeMsg]: Decoded messages.

        Raises:
            ValueError: If the batch is not a JSON array.
        """
        raw = json.loads(line)
        if not isinstance(raw, list):
            raise ValueError("batch must be a JSON array")
        return [cls.from_json_obj(m) for m in raw]

    # ------------------------------------------------------------------
    # Human‑friendly conversion
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Convert this BridgeMsg into a clean Python dict.

        Recursively converts NamedTuples, lists, and dicts into plain
        Python structures suitable for logging or debugging.

        Returns:
            dict: A dictionary with keys "type" and "value".
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
    """Server-side component of the XP DataRef bridge.

    XPBridgeServer runs inside X‑Plane (via XPPython3) and exposes a
    minimal TCP protocol for synchronizing DataRef metadata and values
    with a simless runner. The server is authoritative: it drives the
    heartbeat, owns all metadata, and sends all META/UPDATE messages.

    A single client may connect at a time. When the client disconnects
    or sends RESET, the server performs a full session reset.
    """

    def __init__(
        self,
        xp_interface: XPInterface,
        rate: float = 0.05,
    ) -> None:
        """Initialize the bridge server.

        Args:
            xp_interface (XPInterface):
                The XPPython3 interface used to access real X‑Plane
                DataRefs and logging.

            rate (float, optional):
                Flightloop callback interval in seconds. Defaults to 0.05.
        """
        self.xp: XPInterface = xp_interface
        self.rate: float = rate

        # TCP state
        self.server_sock: Optional[socket.socket] = None
        self.client_sock: Optional[socket.socket] = None
        self.client_file: Optional[TextIO] = None

        # DataRef metadata and manager
        self.specs: Dict[str, DataRefSpec] = {}
        self.manager: DataRefManager = DataRefManager(self.xp, timeout_seconds=0.0)

        # Last-sent values for UPDATE deduplication
        self.last_sent: Dict[int, Any] = {}

        # Path/index mappings
        self._path_to_idx: Dict[str, int] = {}
        self._idx_to_path: Dict[int, str] = {}
        self._next_idx: int = 1

        # Heartbeat (server-driven)
        self._last_activity: float = time.time()

        self._open_server()

    # ------------------------------------------------------------------
    # TCP server lifecycle
    # ------------------------------------------------------------------
    def _open_server(self) -> None:
        """Create and bind the listening TCP socket."""
        self._close_server()

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bind_host = "0.0.0.0"
        srv.bind((bind_host, BRIDGE_PORT))
        srv.listen(1)
        srv.setblocking(False)

        self.server_sock = srv
        self.xp.log(f"[Bridge] listening on {bind_host}:{BRIDGE_PORT}")

    def _close_server(self) -> None:
        """Close the listening socket if open."""
        if self.server_sock:
            self.xp.log("[Bridge] closing server socket")
            try:
                self.server_sock.close()
            except Exception as exc:
                self.xp.log(f"[Bridge] error closing server socket: {exc!r}")
            self.server_sock = None

    def _close_client(self) -> None:
        """Close the active client connection and reset session state."""
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
        """Perform a full session reset.

        Clears all DataRef specs, manager state, last-sent values, and
        index mappings. Used when the client disconnects or sends RESET.
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
    # Unified send path
    # ------------------------------------------------------------------
    def _send_batch(self, msgs: List[BridgeMsg]) -> None:
        """Send a batch of messages to the client.

        Args:
            msgs (List[BridgeMsg]):
                Messages to send. No-op if no client is connected.
        """
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
        """Send an ERROR message to the client."""
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
        """Main server loop executed by X‑Plane.

        Handles:
        - Accepting new clients
        - Reading inbound messages
        - Sending META/UPDATE/PING
        - Heartbeat timeout enforcement

        Returns:
            float: The next flightloop interval.
        """
        now = time.time()

        # Accept new client
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

        # Non-blocking read
        sock = self.client_sock
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
                    self.xp.log(f"[Bridge] invalid JSON batch: {exc!r} line={stripped!r}")
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

        # Heartbeat timeout
        if now - self._last_activity > HEARTBEAT_TIMEOUT:
            self.xp.log("[Bridge] heartbeat timeout — closing client and full reset")
            self._close_client()
            return -1.0

        return self.rate

    # ------------------------------------------------------------------
    # Inbound message handling
    # ------------------------------------------------------------------
    def _process_msg(self, msg: BridgeMsg) -> None:
        """Handle inbound messages from the client."""
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
            # Client acknowledged our PING
            pass

        # META / UPDATE / ERROR / PING are server-originated only

    # ------------------------------------------------------------------
    # Apply ADD — build DataRefSpec and send META
    # ------------------------------------------------------------------
    def _next_index_for_path(self, path: str) -> int:
        """Return the existing or new index for a DataRef path."""
        existing = self._path_to_idx.get(path)
        if existing is not None:
            return existing
        idx = self._next_idx
        self._next_idx += 1
        self._path_to_idx[path] = idx
        self._idx_to_path[idx] = path
        return idx

    def _apply_add(self, path: str) -> None:
        """Handle an ADD request for a DataRef path."""
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
        self.xp.log(f"[Bridge] INFO: {info} type={info.type}")

        # Determine array size
        t = info.type
        if t == int(DRefType.FLOAT_ARRAY):
            array_size = self.xp.getDatavf(handle, None, 0, 0)
        elif t == int(DRefType.INT_ARRAY):
            array_size = self.xp.getDatavi(handle, None, 0, 0)
        elif t == int(DRefType.BYTE_ARRAY):
            array_size = self.xp.getDatab(handle, None, 0, 0)
        else:
            array_size = 0

        # Build spec
        try:
            spec = DataRefSpec.from_info(
                path=path,
                info=info,
                required=False,
                default=None,
                handle=handle,
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
        """Compute UPDATE messages if any DataRef values changed.

        Args:
            counter (int):
                Flightloop counter from X‑Plane.

        Returns:
            Optional[BridgeMsg]: UPDATE message if changes exist, else None.
        """
        if not self.manager.ready():
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
    dtype: Optional[DRefType]  # Only for META
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
        xp_interface: XPInterface,
        host: str = BRIDGE_HOST,
        port: int = BRIDGE_PORT,
    ) -> None:
        self.xp: XPInterface = xp_interface

        # Production defaults (may be overridden by FakeXP)
        self.host: str = host
        self.port: int = port

        # TCP connection state
        self.sock: Optional[socket.socket] = None
        self.file: Optional[TextIO] = None

        # Heartbeat: client enforces timeout based on inbound activity
        self._last_activity: float = 0.0

        # Client-side idx → path mapping (for user-friendly BridgeData events)
        self._idx_to_path: Dict[int, str] = {}

        self._conn_status: str = "Initialized"
        self._prev_conn_status: str = ""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self.sock is not None

    @property
    def conn_status(self) -> str:
        return self._conn_status

    def set_conn_status(self, status: str) -> None:
        self._conn_status = status
        if self._conn_status != self._prev_conn_status:
            self.xp.log(f"[Bridge] {self._conn_status}")

    def connect(self) -> None:
        self.disconnect()

        self.set_conn_status(f"Connecting to {self.host}:{self.port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
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
        self._idx_to_path.clear()

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
        """Request tracking of one or more DataRefs."""
        self._send_batch([BridgeMsg(BridgeMsgType.ADD, Add(paths=list(paths)))])

    def reset(self) -> None:
        """Explicit full reset request; both sides should rebuild state."""
        self._send_batch([BridgeMsg(BridgeMsgType.RESET, Reset())])

    def get_path_for_idx(self, idx: int) -> Optional[str]:
        return self._idx_to_path.get(idx)

    # ------------------------------------------------------------------
    # Poll for inbound messages (wire format)
    # ------------------------------------------------------------------
    RECONNECT_INTERVAL = 30.0  # seconds

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
        now = time.time()

        # --------------------------------------------------------------
        # 1. If disconnected, retry connection every RECONNECT_INTERVAL
        # --------------------------------------------------------------
        if not self.is_connected:
            if now - self._last_activity < RECONNECT_INTERVAL:
                return []
            try:
                self.connect()
            except Exception as exc:
                self.set_conn_status(f"Connect failed to host {BRIDGE_HOST}: {exc}")
                self._last_activity = now
                return []
            self.set_conn_status(f"Processing bridge messages")

        # --------------------------------------------------------------
        # 2. Connected: heartbeat timeout → disconnect + raise
        # --------------------------------------------------------------
        if now - self._last_activity > HEARTBEAT_TIMEOUT:
            self.disconnect()
            self.set_conn_status(f"Heartbeat timeout after {HEARTBEAT_TIMEOUT} seconds")
            raise ConnectionResetError(self.conn_status)

        # --------------------------------------------------------------
        # 3. Check for inbound data (raise on select errors)
        # --------------------------------------------------------------
        rlist, _, _ = select.select([self.sock], [], [], 0)
        if not rlist:
            return []

        # --------------------------------------------------------------
        # 4. Read one line (raise on server close)
        # --------------------------------------------------------------
        line = self.file.readline()
        if line == "":
            self.disconnect()
            self.set_conn_status("Server closed connection")
            raise ConnectionResetError(self.conn_status)

        self._last_activity = now

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
            self._send_batch([BridgeMsg(BridgeMsgType.PONG, Pong())])

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
                        dtype=DRefType(v.type),
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
