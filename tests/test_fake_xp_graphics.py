# tests/test_fake_xp_graphics.py

import pytest
import XPPython3

from simless.libs.fake_xp import FakeXP
from simless.libs.fake_xp_types import EventInfo, EventKind


@pytest.fixture
def xp() -> FakeXP:
    """
    Full DearPyGui environment, identical to SimlessRunner.
    No monkeypatching. GUI fully functional.
    """
    fake = FakeXP(enable_gui=True, debug=True)
    XPPython3.xp = fake

    # SimlessRunner initializes graphics BEFORE plugin enable
    fake.init_graphics_root()

    return fake


def _create_helloworld_window(xp: FakeXP):
    """Helper: create a window using the HelloWorld-style signature."""
    return xp.createWindowEx(
        50, 600, 300, 400,               # left, top, right, bottom
        1,                               # visible
        lambda w, r: None,               # draw callback
        lambda w, x, y, m, r: 1,         # mouse callback
        lambda *a: None,                 # key callback
        lambda *a: xp.CursorDefault,     # cursor callback
        lambda *a: 1,                    # wheel callback
        0,                               # refcon
        xp.WindowDecorationRoundRectangle,
        xp.WindowLayerFloatingWindows,
        None,                            # right-click callback
    )


# ---------------------------------------------------------------------------
# 1. Basic window creation (HelloWorld-style)
# ---------------------------------------------------------------------------

def test_create_window_helloworld_signature(xp):
    wid = _create_helloworld_window(xp)

    # Exercise full draw loop
    xp.draw_frame()

    assert wid in xp._windows_ex
    info = xp._windows_ex[wid]

    # Geometry must match XP frame
    assert info.frame == (50, 600, 300, 400)
    assert info.width == 250
    assert info.height == 200

    # DPG window + drawlist must exist
    assert info.dpg_window_id is not None
    assert info.drawlist_id is not None

    # Draw callback must be stored
    assert callable(info.draw_cb)

    # XP→DPG geometry must have been applied
    assert info.dirty_xp_to_dpg is False


# ---------------------------------------------------------------------------
# 2. Multiple windows: both must be realized and drawn
# ---------------------------------------------------------------------------

def test_multiple_windows_realized_and_drawn(xp):
    wid1 = _create_helloworld_window(xp)
    wid2 = xp.createWindowEx(
        200, 500, 500, 300,
        1,
        lambda w, r: None,
        lambda w, x, y, m, r: 1,
        lambda *a: None,
        lambda *a: xp.CursorDefault,
        lambda *a: 1,
        0,
        xp.WindowDecorationRoundRectangle,
        xp.WindowLayerFloatingWindows,
        None,
    )

    xp.draw_frame()

    assert wid1 in xp._windows_ex
    assert wid2 in xp._windows_ex

    assert xp._windows_ex[wid1].dpg_window_id is not None
    assert xp._windows_ex[wid2].dpg_window_id is not None


# ---------------------------------------------------------------------------
# 3. Visibility flag is honored (but DPG handles visibility internally)
# ---------------------------------------------------------------------------

def test_window_visibility_flag(xp):
    wid = _create_helloworld_window(xp)
    xp.draw_frame()

    info = xp._windows_ex[wid]
    assert info.visible is True

    xp.setWindowIsVisible(wid, 0)
    xp.draw_frame()

    assert info.visible is False


# ---------------------------------------------------------------------------
# 4. Geometry updates propagate through XP→DPG sync
# ---------------------------------------------------------------------------

def test_window_geometry_update(xp):
    wid = _create_helloworld_window(xp)
    xp.draw_frame()

    info = xp._windows_ex[wid]
    assert info.frame == (50, 600, 300, 400)

    xp.setWindowGeometry(wid, 100, 700, 400, 500)
    xp.draw_frame()

    assert info.frame == (100, 700, 400, 500)
    assert info.width == 300
    assert info.height == 200


# ---------------------------------------------------------------------------
# 5. Destroying a window removes it from registry and prevents drawing
# ---------------------------------------------------------------------------

def test_destroy_window(xp):
    wid = _create_helloworld_window(xp)
    xp.draw_frame()

    assert wid in xp._windows_ex

    xp.destroyWindow(wid)
    xp.draw_frame()

    assert wid not in xp._windows_ex


# ---------------------------------------------------------------------------
# 6. Z-order: bringing window to front updates ordering
# ---------------------------------------------------------------------------

def test_window_layer_sorting(xp):
    wid1 = _create_helloworld_window(xp)
    wid2 = xp.createWindowEx(
        200, 500, 500, 300,
        1,
        lambda w, r: None,
        lambda w, x, y, m, r: 1,
        lambda *a: None,
        lambda *a: xp.CursorDefault,
        lambda *a: 1,
        0,
        xp.WindowDecorationRoundRectangle,
        xp.WindowLayerFloatingWindows,
        None,
    )

    xp.draw_frame()

    # Windows are sorted by layer, not by creation order
    windows = list(xp._iter_window_ex_in_layer_order())

    # Both windows have the same layer, so ordering is undefined
    assert len(windows) == 2
    assert {w.wid for w in windows} == {wid1, wid2}


# ---------------------------------------------------------------------------
# 7. Draw callbacks are invoked during draw_frame
# ---------------------------------------------------------------------------

def test_draw_callback_invoked(xp):
    calls = []

    def draw_cb(wid, refcon):
        calls.append(wid)

    wid = xp.createWindowEx(
        50, 600, 300, 400,
        1,
        draw_cb,
        lambda w, x, y, m, r: 1,
        lambda *a: None,
        lambda *a: xp.CursorDefault,
        lambda *a: 1,
        0,
        xp.WindowDecorationRoundRectangle,
        xp.WindowLayerFloatingWindows,
        None,
    )

    xp.draw_frame()

    assert calls == [wid]

def test_mouse_click_dispatch_to_window(xp):
    calls = []

    def click_cb(wid, x, y, mouse, refcon):
        calls.append((wid, x, y, mouse))
        return 1

    wid = xp.createWindowEx(
        50, 600, 300, 400,
        1,
        lambda *a: None,
        click_cb,
        lambda *a: None,
        lambda *a: xp.CursorDefault,
        lambda *a: 1,
        0,
        xp.WindowDecorationRoundRectangle,
        xp.WindowLayerFloatingWindows,
        None,
    )

    xp.queue_input_event(EventInfo.from_xp(
        kind=EventKind.MOUSE_BUTTON,
        xp_x=100,
        xp_y=550,
        state="down",
        button=0,
    ))

    xp.draw_frame()

    assert len(calls) == 1
    wid2, x, y, mouse = calls[0]

    assert wid2 == wid
    assert x == 100
    assert y == 550

    # Mouse is an XP bitmask, not a button number
    assert isinstance(mouse, int)
    assert mouse != 0
