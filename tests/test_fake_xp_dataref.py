# tests/test_fake_xp_dataref.py
import pytest
from typing import List

import XPPython3
from simless.libs.fake_xp import FakeXP
from simless.libs.fake_xp_dataref import (
    FakeDataRef,
    DRefType,
    Type_Float,
    Type_Int,
)


@pytest.fixture
def xp() -> FakeXP:
    """Create a FakeXP façade and initialize the global XPPython3.xp as tests expect."""
    fake = FakeXP(debug=True)
    # Bind into XPPython3 global as production code expects
    XPPython3.xp = fake
    return fake


def test_find_and_dummy_creation(xp: FakeXP):
    ref = xp.findDataRef("sim/test/float_scalar")
    assert isinstance(ref, FakeDataRef)
    assert ref.path == "sim/test/float_scalar"
    assert ref.is_dummy is True
    assert ref.type == DRefType.FLOAT
    assert ref.size == 1
    assert ref.value == 0.0


def test_get_dataref_types_and_info(xp: FakeXP):
    ref = xp.findDataRef("sim/test/float_scalar2")
    tmask = xp.getDataRefTypes(ref)
    assert tmask & Type_Float
    info = xp.getDataRefInfo(ref)
    assert info.name == ref.path
    assert info.type == tmask
    assert info.is_array is False
    assert info.size == 1


def test_can_write_and_is_good(xp: FakeXP):
    ref = xp.findDataRef("sim/test/writable")
    assert xp.canWriteDataRef(ref) is True
    assert xp.isDataRefGood(ref) is True

    xp.update_dataref(ref, dtype=DRefType.FLOAT, size=1, value=1.23)
    assert ref.value == pytest.approx(1.23)

    reg = xp.registerDataAccessor(
        "sim/test/writable",
        readFloat=lambda rc: 1.23,
        writeFloat=lambda rc, v: None,
    )
    assert xp.canWriteDataRef(reg) is True
    assert xp.isDataRefGood(reg) is True


def test_register_and_unregister_accessor_scalar(xp: FakeXP):
    def my_read_int(rc):
        return 42

    written = {}

    def my_write_int(rc, v):
        written["v"] = v

    ref = xp.registerDataAccessor(
        "myplugin/int_item",
        readInt=my_read_int,
        writeInt=my_write_int,
    )
    assert xp.getDataRefTypes(ref) & Type_Int
    assert xp.getDatai(ref) == 42
    xp.setDatai(ref, 99)
    assert written["v"] == 99

    xp.unregisterDataAccessor(ref)
    with pytest.raises(TypeError):
        xp.getDatai(ref)
    assert xp.isDataRefGood(ref) is False


def test_array_accessors_and_semantics(xp: FakeXP):
    initial = [0.1 * i for i in range(8)]

    def read_float_array(rc, out, offset, count):
        for i in range(count):
            out[i] = initial[offset + i]
        return count

    written = {}

    def write_float_array(rc, values, offset, count):
        written["buf"] = list(values[:count])

    ref = xp.registerDataAccessor(
        "myplugin/float_array",
        readFloatArray=read_float_array,
        writeFloatArray=write_float_array,
    )

    assert xp.getDatavf(ref, None, 0, -1) == 8

    out: List[float] = [0.0] * 4
    copied = xp.getDatavf(ref, out, offset=2, count=4)
    assert copied == 4
    assert out == initial[2:6]

    with pytest.raises(RuntimeError):
        xp.setDatavf(ref, [1.0, 2.0], offset=0, count=4)

    xp.setDatavf(ref, [9.0, 8.0, 7.0, 6.0], offset=0, count=4)
    assert written["buf"] == [9.0, 8.0, 7.0, 6.0]


def test_byte_array_and_string_helpers(xp: FakeXP):
    initial_bytes = bytearray(b"Hello\x00" + b"\x00" * 10)
    ref = xp.registerDataAccessor(
        "myplugin/bytes",
        readData=lambda rc, out, off, cnt: 0,
        writeData=lambda rc, v, off, cnt: None,
    )

    with xp._handles_lock:
        h = xp._handles[ref.path]
        h.type = DRefType.BYTE_ARRAY
        h.value = initial_bytes
        h.size = len(initial_bytes)

    s = xp.getDatas(ref)
    assert s.startswith("Hello")

    xp.setDatas(ref, "ABC", offset=0, count=5)
    with xp._handles_lock:
        buf = xp._handles[ref.path].value
    assert bytes(buf[:5]).startswith(b"ABC")

    assert xp.getDatab(ref, None, 0, -1) == len(buf)


def test_promotion_preserves_dummy_writes(xp: FakeXP):
    ref = xp.findDataRef("sim/test/promo")
    assert ref.is_dummy

    xp.update_dataref(
        ref,
        dtype=DRefType.FLOAT_ARRAY,
        size=4,
        value=[1.0, 2.0, 3.0, 4.0],
    )
    assert ref.value == [1.0, 2.0, 3.0, 4.0]

    xp.promote_handle(
        ref,
        dtype=DRefType.FLOAT_ARRAY,
        is_array=True,
        size=4,
        writable=True,
        preserve_dummy_writes=True,
    )
    assert ref.is_dummy is False
    assert ref.value == [1.0, 2.0, 3.0, 4.0]

    ref2 = xp.findDataRef("sim/test/promo2")
    xp.update_dataref(ref2, dtype=DRefType.FLOAT, size=1, value=0.5)

    xp.promote_handle(
        ref2,
        dtype=DRefType.FLOAT_ARRAY,
        is_array=True,
        size=4,
        writable=True,
    )
    assert ref2.is_dummy is False
    assert isinstance(ref2.value, list)
    assert len(ref2.value) == 4


def test_update_dummy_ref_validation(xp: FakeXP):
    ref = xp.findDataRef("sim/test/update_dummy")
    with pytest.raises(ValueError):
        xp.update_dataref(ref, size=0)

    reg = xp.registerDataAccessor(
        "sim/test/update_dummy",
        readFloat=lambda rc: 0.0,
    )
    xp.update_dataref(
        reg,
        dtype=DRefType.FLOAT_ARRAY,
        size=4,
        value=[1, 2, 3, 4],
    )
    assert reg.type == DRefType.FLOAT_ARRAY
    assert reg.size == 4


def test_dummy_set_grows_backing_array(xp: FakeXP):
    ref = xp.findDataRef("sim/test/dummy_grow")
    assert ref.is_dummy

    xp.update_dataref(
        ref,
        dtype=DRefType.FLOAT_ARRAY,
        size=2,
        value=[1.0, 2.0],
    )
    assert ref.value == [1.0, 2.0]
    assert ref.size == 2

    xp.setDatavf(ref, [9.0, 8.0, 7.0], offset=0, count=3)
    assert ref.is_dummy
    assert ref.value == [9.0, 8.0, 7.0]
    assert ref.size == 3


def test_promoted_set_enforces_inplace_bounds(xp: FakeXP):
    initial = [0.5 * i for i in range(8)]

    def read_float_array(rc, out, offset, count):
        for i in range(count):
            out[i] = initial[offset + i]
        return count

    written = {}

    def write_float_array(rc, values, offset, count):
        written["buf"] = list(values[:count])

    ref = xp.registerDataAccessor(
        "myplugin/real_array",
        readFloatArray=read_float_array,
        writeFloatArray=write_float_array,
    )

    assert ref.is_dummy is False

    with pytest.raises(RuntimeError):
        xp.setDatavf(ref, [1.0] * 16, offset=0, count=16)

    xp.setDatavf(ref, [9.0, 8.0, 7.0, 6.0], offset=0, count=4)
    assert written["buf"] == [9.0, 8.0, 7.0, 6.0]


def test_promote_merges_or_replaces_dummy_writes(xp: FakeXP):
    ref = xp.findDataRef("sim/test/preserve_merge")
    xp.update_dataref(
        ref,
        dtype=DRefType.FLOAT_ARRAY,
        size=3,
        value=[1.0, 2.0, 3.0],
    )
    assert ref.is_dummy

    xp.promote_handle(
        ref,
        dtype=DRefType.FLOAT_ARRAY,
        is_array=True,
        size=3,
        writable=True,
        preserve_dummy_writes=True,
    )
    assert ref.is_dummy is False
    assert ref.value == [1.0, 2.0, 3.0]

    ref2 = xp.findDataRef("sim/test/preserve_replace")
    xp.update_dataref(
        ref2,
        dtype=DRefType.FLOAT_ARRAY,
        size=4,
        value=[7.0, 7.0, 7.0, 7.0],
    )
    assert ref2.is_dummy

    xp.promote_handle(
        ref2,
        dtype=DRefType.FLOAT_ARRAY,
        is_array=True,
        size=6,
        writable=True,
        preserve_dummy_writes=False,
    )
    assert ref2.is_dummy is False
    assert isinstance(ref2.value, list)
    assert len(ref2.value) >= 6
    assert ref2.value[0] == pytest.approx(0.0)


def test_getDatavf_offset_and_count_write_into_buffer(xp: FakeXP):
    base = [i + 0.1 for i in range(8)]

    def read_float_array(rc, out, offset, count):
        for i in range(count):
            out[i] = base[offset + i]
        return count

    ref = xp.registerDataAccessor(
        "myplugin/offset_array",
        readFloatArray=read_float_array,
    )

    assert xp.getDatavf(ref, None, 0, -1) == 8

    buf: List[float] = [0.0] * 10
    got = xp.getDatavf(ref, buf, offset=2, count=4)
    assert got == 4
    assert buf[2:6] == base[2:6]


def test_setDatab_dummy_and_real_semantics(xp: FakeXP):
    ref = xp.findDataRef("sim/test/bytes_dummy")
    xp.update_dataref(
        ref,
        dtype=DRefType.BYTE_ARRAY,
        size=4,
        value=bytearray(b"ABCD"),
    )
    assert ref.is_dummy

    xp.setDatab(
        ref,
        [ord("X"), ord("Y"), ord("Z"), ord("!"), ord("?")],
        offset=0,
        count=5,
    )
    assert bytes(ref.value[:5]) == b"XYZ!?"

    def read_data(rc, out, off, cnt):
        for i in range(cnt):
            out[i] = i + 1
        return cnt

    def write_data(rc, values, off, cnt):
        return

    real = xp.registerDataAccessor(
        "myplugin/real_bytes",
        readData=read_data,
        writeData=write_data,
    )
    assert real.is_dummy is False

    with pytest.raises(RuntimeError):
        xp.setDatab(real, [0] * 512, offset=0, count=512)
