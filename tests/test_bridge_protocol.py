import pytest

from sshd_extensions.bridge_protocol import (
    BridgeMsg,
    BridgeMsgType,
    Meta,
    Update,
    UpdateEntry,
    Add,
    Reset,
    Ping,
    Pong,
    ErrorMsg,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def roundtrip(msg: BridgeMsg) -> BridgeMsg:
    """Encode → decode a single message."""
    encoded = msg.to_json_obj()
    decoded = BridgeMsg.from_json_obj(encoded)
    return decoded


def batch_roundtrip(msgs):
    encoded = BridgeMsg.encode_batch(msgs).decode("utf-8").strip()
    decoded = BridgeMsg.decode_batch(encoded)
    return decoded


# ---------------------------------------------------------------------------
# Basic message construction
# ---------------------------------------------------------------------------

def test_meta_roundtrip():
    m = BridgeMsg(BridgeMsgType.META, Meta(1, "sim/foo", 5, False, 0))
    out = roundtrip(m)
    assert out.type is BridgeMsgType.META
    assert out.value == m.value


def test_update_roundtrip():
    u = Update([UpdateEntry(3, 42.0), UpdateEntry(7, [1, 2, 3])])
    m = BridgeMsg(BridgeMsgType.UPDATE, u)
    out = roundtrip(m)
    assert out.type is BridgeMsgType.UPDATE
    assert out.value.entries == u.entries


def test_add_roundtrip():
    m = BridgeMsg(BridgeMsgType.ADD, Add(paths=["a", "b", "c"]))
    out = roundtrip(m)
    assert out.type is BridgeMsgType.ADD
    assert out.value.paths == ["a", "b", "c"]


def test_reset_roundtrip():
    m = BridgeMsg(BridgeMsgType.RESET, Reset())
    out = roundtrip(m)
    assert out.type is BridgeMsgType.RESET


def test_ping_pong_roundtrip():
    assert roundtrip(BridgeMsg(BridgeMsgType.PING, Ping())).type is BridgeMsgType.PING
    assert roundtrip(BridgeMsg(BridgeMsgType.PONG, Pong())).type is BridgeMsgType.PONG


def test_error_roundtrip():
    m = BridgeMsg(BridgeMsgType.ERROR, ErrorMsg("bad thing"))
    out = roundtrip(m)
    assert out.type is BridgeMsgType.ERROR
    assert out.value.text == "bad thing"


# ---------------------------------------------------------------------------
# Batch encoding/decoding
# ---------------------------------------------------------------------------

def test_batch_roundtrip():
    msgs = [
        BridgeMsg(BridgeMsgType.PING, Ping()),
        BridgeMsg(BridgeMsgType.ADD, Add(paths=["x"])),
        BridgeMsg(BridgeMsgType.ERROR, ErrorMsg("oops")),
    ]
    out = batch_roundtrip(msgs)
    assert len(out) == 3
    assert out[0].type is BridgeMsgType.PING
    assert out[1].value.paths == ["x"]
    assert out[2].value.text == "oops"


# ---------------------------------------------------------------------------
# to_dict() formatting
# ---------------------------------------------------------------------------

def test_to_dict_meta():
    m = BridgeMsg(BridgeMsgType.META, Meta(1, "sim/foo", 5, False, 0))
    d = m.to_dict()
    assert d == {
        "type": "meta",
        "value": {
            "idx": 1,
            "name": "sim/foo",
            "type": 5,
            "writable": False,
            "array_size": 0,
        },
    }


def test_to_dict_update():
    u = Update([UpdateEntry(3, 99)])
    m = BridgeMsg(BridgeMsgType.UPDATE, u)
    d = m.to_dict()
    assert d == {
        "type": "update",
        "value": {
            "entries": [{"idx": 3, "value": 99}],
        },
    }


# ---------------------------------------------------------------------------
# Registry correctness
# ---------------------------------------------------------------------------

def test_registry_contains_all_types():
    for t in BridgeMsgType:
        assert t in BridgeMsg._registry


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_decode_invalid_message_type():
    with pytest.raises(ValueError):
        BridgeMsg.from_json_obj(["not-a-type", {}])


def test_decode_invalid_payload_shape():
    # META requires 5 fields
    with pytest.raises(Exception):
        BridgeMsg.from_json_obj(["meta", [1, 2]])
