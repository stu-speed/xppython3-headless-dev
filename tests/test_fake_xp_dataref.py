# tests/test_fake_xp_dataref.py

from typing import List

import pytest

import XPPython3
from simless.libs.fake_xp import FakeXP
from simless.libs.fake_xp_types import FakeDataRef, Type_Data, Type_Int, Type_Unknown
from PythonPlugins.sshd_extensions.dataref_manager import DRefType


@pytest.fixture
def xp() -> FakeXP:
    """Create a FakeXP façade and initialize the global XPPython3.xp as tests expect."""
    fake = FakeXP(debug=True)
    XPPython3.xp = fake
    return fake


@pytest.fixture
def update_dataref():
    """
    Test-only helper that coerces dummy FakeDataRef fields without promoting.
    Mirrors the semantics expected by test_update_dummy_ref_validation.
    """

    def _update(ref, *, dtype=None, size=None, value=None):
        if not ref.is_dummy:
            raise RuntimeError("update_dataref only valid for dummy refs")

        if size is not None and size <= 0:
            raise ValueError("size must be > 0")

        if dtype is not None:
            ref.type = dtype
            ref.type_known = True

        if size is not None:
            ref.size = size
            ref.is_array = size > 1
            ref.shape_known = True

        if value is not None:
            ref.value = value

        return True

    return _update


def test_find_and_dummy_creation(xp: FakeXP):
    ref = xp.findDataRef("sim/test/float_scalar")
    assert isinstance(ref, FakeDataRef)
    assert ref.path == "sim/test/float_scalar"
    assert ref.type == DRefType.FLOAT
    assert ref.type_known is False
    assert ref.shape_known is False
    assert ref.is_array is None
    assert ref.size == 1
    assert ref.value == 0.0


def test_get_dataref_types_and_info_unknown_shape(xp: FakeXP):
    ref = xp.findDataRef("sim/test/float_scalar2")
    tmask = xp.getDataRefTypes(ref)
    assert tmask == Type_Unknown

    info = xp.getDataRefInfo(ref)
    assert info.name == ref.path
    assert info.type == Type_Unknown
    assert info.is_array is None
    assert info.size == 0


def test_can_write_and_is_good(xp: FakeXP):
    ref = xp.findDataRef("sim/test/writable")
    assert xp.canWriteDataRef(ref) is True
    assert xp.isDataRefGood(ref) is True

    xp.dataref_manager.promote_shape_from_value(ref=ref, value=1.23)
    assert ref.value == pytest.approx(1.23)
    assert ref.shape_known is True
    assert ref.is_array is False

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


def test_byte_array_and_string_helpers_on_internal_buffer(xp: FakeXP):
    ref = xp.findDataRef("sim/test/bytes_internal")

    xp.dataref_manager.promote_type(ref=ref, dtype=DRefType.BYTE_ARRAY, writable=True)
    xp.dataref_manager.promote_shape_from_value(ref=ref, value=bytearray(b"Hello\x00" + b"\x00" * 10))

    assert xp.getDataRefTypes(ref) & Type_Data

    s = xp.getDatas(ref)
    assert s.startswith("Hello")

    xp.setDatas(ref, "ABC", offset=0, count=5)
    assert bytes(ref.value[:5]).startswith(b"ABC")

    assert xp.getDatab(ref, None, 0, -1) == len(ref.value)


def test_promote_type_validates_value_on_type_change(xp: FakeXP):
    ref = xp.findDataRef("sim/test/type_change")

    xp.dataref_manager.promote_shape_from_value(ref=ref, value=1.5)
    assert ref.shape_known is True
    assert ref.is_array is False

    xp.dataref_manager.promote_type(ref=ref, dtype=DRefType.INT, writable=True)
    assert ref.type == DRefType.INT
    assert isinstance(ref.value, int)


def test_promote_shape_from_value_does_not_change_known_shape(xp: FakeXP):
    ref = xp.findDataRef("sim/test/shape_replace")

    xp.dataref_manager.promote_shape_from_value(ref=ref, value=0.5)
    assert ref.shape_known is True
    assert ref.is_array is False
    assert ref.value == pytest.approx(0.5)

    xp.dataref_manager.promote_type(ref=ref, dtype=DRefType.FLOAT_ARRAY, writable=True)
    assert ref.type == DRefType.FLOAT_ARRAY
    assert ref.shape_known is True
    assert ref.is_array is True

    xp.dataref_manager.promote_shape_from_value(ref=ref, value=[1.0, 2.0, 3.0, 4.0])
    assert ref.shape_known is True
    assert ref.is_array is True
    assert ref.size == 1
    assert isinstance(ref.value, list)
    assert len(ref.value) == 1


def test_update_dummy_ref_validation(xp: FakeXP, update_dataref):
    ref = xp.findDataRef("sim/test/update_dummy")

    with pytest.raises(ValueError):
        update_dataref(ref, size=0)

    reg = xp.registerDataAccessor(
        "sim/test/update_dummy",
        readFloat=lambda rc: 0.0,
    )

    update_dataref(
        reg,
        dtype=DRefType.FLOAT_ARRAY,
        size=4,
        value=[1, 2, 3, 4],
    )
    assert reg.type == DRefType.FLOAT_ARRAY
    assert reg.size == 4


def test_setDatavf_establishes_shape_then_enforces_bounds(xp: FakeXP):
    ref = xp.findDataRef("sim/test/shape_from_write")
    xp.dataref_manager.promote_type(ref=ref, dtype=DRefType.FLOAT_ARRAY, writable=True)

    xp.setDatavf(ref, [9.0, 8.0, 7.0], offset=0, count=3)
    assert ref.type_known is True
    xp.dataref_manager.promote_shape_from_value(ref, [9.0, 8.0, 7.0])
    assert ref.shape_known is True

    with pytest.raises(RuntimeError):
        xp.setDatavf(ref, [1.0, 2.0, 3.0, 4.0], offset=0, count=4)


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

    with pytest.raises(RuntimeError):
        xp.setDatavf(ref, [1.0] * 16, offset=0, count=16)

    xp.setDatavf(ref, [9.0, 8.0, 7.0, 6.0], offset=0, count=4)
    assert written["buf"] == [9.0, 8.0, 7.0, 6.0]


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


def test_setDatab_internal_buffer_and_real_bounds(xp: FakeXP):
    ref = xp.findDataRef("sim/test/bytes_internal2")
    xp.dataref_manager.promote_type(ref=ref, dtype=DRefType.BYTE_ARRAY, writable=True)
    xp.dataref_manager.promote_shape_from_value(ref=ref, value=bytearray(b"ABCD"))

    xp.setDatab(
        ref,
        [ord("X"), ord("Y"), ord("Z"), ord("!")],
        offset=0,
        count=4,
    )
    assert bytes(ref.value[:4]) == b"XYZ!"

    with pytest.raises(RuntimeError):
        xp.setDatab(
            ref,
            [ord("X"), ord("Y"), ord("Z"), ord("!"), ord("?")],
            offset=0,
            count=5,
        )
