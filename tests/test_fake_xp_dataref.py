# tests/test_fake_xp_dataref.py

from typing import List
import pytest

import XPPython3
from simless.libs.fake_xp import FakeXP
from simless.libs.fake_xp_types import FakeDataRef


@pytest.fixture
def xp() -> FakeXP:
    fake = FakeXP(debug_logging=True)
    XPPython3.xp = fake
    return fake


# ================================================================
#  BASIC FIND + DUMMY CREATION
# ================================================================

def test_find_and_dummy_creation(xp: FakeXP):
    dr = xp.findDataRef("sim/test/float_scalar")
    ref = xp.dataref_manager.require_handle(dr)

    assert isinstance(ref, FakeDataRef)
    assert ref.path == "sim/test/float_scalar"
    assert ref.type == xp.Type_Float
    assert ref.is_array is False
    assert ref.size == 1
    assert ref.value == 0.0


def test_dummy_scalar_recasts_then_expands_but_stays_dummy(xp: FakeXP):
    dr = xp.findDataRef("sim/test/dummy_scalar_to_array")
    ref = xp.dataref_manager.require_handle(dr)

    # First GET should recast dummy scalar → dummy array [0.0]
    length = xp.getDatavf(dr)
    assert length == 1

    assert ref.dummy
    assert ref.size == 1
    assert ref.value == [0.0]

    # Expand via API
    xp.setDatavf(dr, [1.2], offset=3, count=1)

    assert ref.dummy
    assert ref.size == 4
    assert ref.value == [0.0, 0.0, 0.0, 1.2]


# ================================================================
#  TYPE MASK + INFO
# ================================================================

def test_get_dataref_types_and_info(xp: FakeXP):
    dr = xp.findDataRef("sim/test/float_scalar2")
    ref = xp.dataref_manager.require_handle(dr)

    assert xp.getDataRefTypes(dr) == xp.Type_Float

    info = xp.getDataRefInfo(dr)
    assert info.name == ref.path
    assert info.type == xp.Type_Float
    assert info.is_array is False
    assert info.size == 0


# ================================================================
#  CAN WRITE + IS GOOD + PROMOTION
# ================================================================

def test_can_write_and_is_good(xp: FakeXP):
    dr = xp.findDataRef("sim/test/writable")
    ref = xp.dataref_manager.require_handle(dr)

    assert xp.canWriteDataRef(dr) is True
    assert xp.isDataRefGood(dr) is True

    # Promote to real scalar float
    xp.dataref_manager.promote(ref, xp.Type_Float, writable=True, array_size=1)
    xp.setDataf(dr, 1.23)

    assert ref.value == pytest.approx(1.23)
    assert ref.is_array is False

    # Accessor-backed version
    reg = xp.registerDataAccessor(
        "sim/test/writable",
        readFloat=lambda rc: 1.23,
        writeFloat=lambda rc, v: None,
    )

    assert xp.canWriteDataRef(reg) is True
    assert xp.isDataRefGood(reg) is True


# ================================================================
#  INTERNAL BYTE ARRAY + STRING HELPERS
# ================================================================

def test_byte_array_and_string_helpers_on_internal_buffer(xp: FakeXP):
    dr = xp.findDataRef("sim/test/bytes_internal")
    ref = xp.dataref_manager.require_handle(dr)

    xp.dataref_manager.promote(ref, xp.Type_Data, writable=True, array_size=16)
    xp.setDatab(dr, list(b"Hello\x00" + b"\x00" * 10))

    assert xp.getDataRefTypes(dr) & xp.Type_Data

    s = xp.getDatas(dr)
    assert s.startswith("Hello")

    xp.setDatas(dr, "ABC", offset=0, count=5)
    assert bytes(ref.value[:5]).startswith(b"ABC")

    assert xp.getDatab(dr, None, 0, -1) == len(ref.value)


# ================================================================
#  ARRAY WRITE SHAPE ESTABLISHMENT + BOUNDS
# ================================================================

def test_setDatavf_establishes_shape_then_enforces_bounds(xp: FakeXP):
    dr = xp.findDataRef("sim/test/shape_from_write")
    ref = xp.dataref_manager.require_handle(dr)

    # Canonical float array of size 3
    xp.dataref_manager.promote(ref, xp.Type_FloatArray, writable=True, array_size=3)

    # Initial write: fills indices 0,1,2
    xp.setDatavf(dr, [9.0, 8.0, 7.0])

    # Partial write: offset=2, count=4 → only index 2 is writable
    # Expected behavior: write 5.0 at index 2, ignore the rest
    xp.setDatavf(dr, [5.0, 2.0, 3.0, 4.0], 2, 4)

    # Read back into an initially empty buffer
    buf = []
    x = xp.getDatavf(dr, buf, 2, 4)

    # Only one element fits
    assert x == 1

    # Buffer must have been expanded and filled
    assert buf == [5.0]


# ================================================================
#  OFFSET + COUNT READ INTO BUFFER
# ================================================================

def test_getDatavf_offset_and_count_write_into_buffer(xp: FakeXP):
    base = [i + 0.1 for i in range(8)]

    def read_float_array(rc, out, offset, count):
        for i in range(count):
            out[i] = base[offset + i]
        return count

    dr = xp.registerDataAccessor(
        "myplugin/offset_array",
        readFloatArray=read_float_array,
    )

    # Accessor-backed: values=None → return full size
    assert xp.getDatavf(dr, None, 0, -1) == 8

    buf = [0.0] * 10
    got = xp.getDatavf(dr, buf, 2, 4)

    # Accessor returns exactly 4 elements
    assert got == 4

    # And they must be written starting at buf[offset]
    assert buf[0:6] == base[2:6]

# ================================================================
#  INTERNAL BYTE ARRAY WRITE + BOUNDS
# ================================================================

def test_setDatab_internal_buffer_and_real_bounds(xp: FakeXP):
    dr = xp.findDataRef("sim/test/bytes_internal2")
    ref = xp.dataref_manager.require_handle(dr)

    xp.dataref_manager.promote(ref, xp.Type_Data, writable=True, array_size=4)
    xp.setDatab(dr, list(b"ABCD"))

    xp.setDatab(dr, [ord("X"), ord("Y"), ord("Z"), ord("!")], 0, 4)
    assert bytes(ref.value[:4]) == b"XYZ!"

    with pytest.raises(ValueError):
        xp.setDatab(dr, [ord("X"), ord("Y"), ord("Z"), ord("!"), ord("?")], 0, 5)


# ================================================================
#  ACCESSOR SCALAR READ/WRITE
# ================================================================

def test_register_and_unregister_accessor_scalar(xp: FakeXP):
    written = {}

    def read_int(rc):
        return 42

    def write_int(rc, v):
        written["v"] = v

    dr = xp.registerDataAccessor(
        "myplugin/int_item",
        readInt=read_int,
        writeInt=write_int,
    )

    # Accessor works
    assert xp.getDataRefTypes(dr) & xp.Type_Int
    assert xp.getDatai(dr) == 42

    xp.setDatai(dr, 99)
    assert written["v"] == 99

    # Unregister → scalar accessor-backed dataref becomes invalid
    xp.unregisterDataAccessor(dr)

    with pytest.raises(ValueError):
        xp.getDatai(dr)

    assert xp.isDataRefGood(dr) is False


# ================================================================
#  ACCESSOR ARRAY WRITE BOUNDS
# ================================================================

def test_promoted_set_enforces_inplace_bounds(xp: FakeXP):
    initial = [0.5 * i for i in range(8)]
    written = {}

    def read_float_array(rc, out, offset, count):
        for i in range(count):
            out[i] = initial[offset + i]
        return count

    def write_float_array(rc, values, offset, count):
        # Accessor decides what to do; X‑Plane does not enforce bounds.
        # For this test, we simulate clipping to accessor-defined length.
        max_len = len(initial)
        n = min(count, max_len - offset)
        written["buf"] = list(values[:n])
        return n

    dr = xp.registerDataAccessor(
        "myplugin/real_array",
        readFloatArray=read_float_array,
        writeFloatArray=write_float_array,
    )

    # Caller tries to write beyond accessor-defined length → accessor clips
    xp.setDatavf(dr, [1.0] * 16, 0, 16)
    assert written["buf"] == [1.0] * 8

    # Valid write
    xp.setDatavf(dr, [9.0, 8.0, 7.0, 6.0], 0, 4)
    assert written["buf"] == [9.0, 8.0, 7.0, 6.0]



# ================================================================
#  ACCESSOR ARRAY READ/WRITE
# ================================================================

def test_array_accessors_and_semantics(xp: FakeXP):
    initial = [0.1 * i for i in range(8)]
    written = {}

    def read_float_array(rc, out, offset, count):
        for i in range(count):
            out[i] = initial[offset + i]
        return count

    def write_float_array(rc, values, offset, count):
        # Accessor receives exactly `count` values.
        written["buf"] = list(values[:count])

    dr = xp.registerDataAccessor(
        "myplugin/float_array",
        readFloatArray=read_float_array,
        writeFloatArray=write_float_array,
    )

    # Length probe: values=None → return length
    assert xp.getDatavf(dr, None, 0, -1) == 8

    # ACCESSOR READ: caller buffer too small → NO RAISE
    out = [0.0] * 4
    xp.getDatavf(dr, out, 2, 4)
    assert out == initial[2:6]

    # Write: caller must supply at least count values (XPPython3 rule)
    with pytest.raises(ValueError):
        xp.setDatavf(dr, [1.0, 2.0], 0, 4)

    # Valid write
    xp.setDatavf(dr, [9.0, 8.0, 7.0, 6.0], 0, 4)
    assert written["buf"] == [9.0, 8.0, 7.0, 6.0]


# ================================================================
#  ACCESSOR PRECEDENCE TEST (ADDED)
# ================================================================

def test_accessor_precedence_over_internal_storage(xp: FakeXP):
    internal = [10.0, 20.0, 30.0, 40.0]
    written = {}

    dr = xp.findDataRef("sim/test/accessor_precedence")
    ref = xp.dataref_manager.require_handle(dr)

    # Establish internal storage via API
    xp.dataref_manager.promote(ref, xp.Type_FloatArray, writable=True, array_size=4)
    xp.setDatavf(dr, internal)

    def read_arr(rc, out, offset, count):
        for i in range(count):
            out[i] = 99.0 + offset + i
        return count

    def write_arr(rc, values, offset, count):
        written["buf"] = list(values[:count])

    reg = xp.registerDataAccessor(
        "sim/test/accessor_precedence",
        readFloatArray=read_arr,
        writeFloatArray=write_arr,
    )

    out = [0.0] * 4
    xp.getDatavf(reg, out, 0, 4)
    assert out == [99.0, 100.0, 101.0, 102.0]

    xp.setDatavf(reg, [1.0, 2.0, 3.0, 4.0], 0, 4)
    assert written["buf"] == [1.0, 2.0, 3.0, 4.0]

    xp.unregisterDataAccessor(reg)

    out2 = [0.0] * 4
    xp.getDatavf(dr, out2, 0, 4)
    assert out2 == internal
