# simless/libs/fake_xp/flightloops.py
# ===========================================================================
# FlightLoop subsystem — xp.* flightloop API, backed by FakeXPRunner.
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, Sequence, TYPE_CHECKING

from XPPython3.xp_typing import XPLMFlightLoopID  # type: ignore[import]

if TYPE_CHECKING:
    from simless.libs.fake_xp.fakexp import FakeXP


class FlightLoopAPI:
    public_api_names = [
        "createFlightLoop",
        "scheduleFlightLoop",
        "destroyFlightLoop",
    ]

    def __init__(self, xp: FakeXP) -> None:
        self.xp = xp

    def createFlightLoop(
        self,
        callback_or_tuple: Callable[[float, float, int, Any], float] | Sequence[Any],
        phase: int = 0,
        refCon: Any | None = None,
    ) -> XPLMFlightLoopID:
        if isinstance(callback_or_tuple, (list, tuple)):
            if len(callback_or_tuple) != 3:
                raise TypeError("FlightLoop tuple must be (phase, callback, refCon)")
            phase, cb, refCon = callback_or_tuple
            if not callable(cb):
                raise TypeError("FlightLoop callback must be callable")
        else:
            cb = callback_or_tuple
            if not callable(cb):
                raise TypeError("First argument to createFlightLoop must be a callback")

        if self.xp._runner is None:
            raise RuntimeError("FakeXP runner not initialized before createFlightLoop")

        struct = {
            "structSize": 1,
            "phase": int(phase),
            "callback": cb,
            "refcon": refCon,
        }

        fl_id_int = self.xp._runner.create_flightloop(1, struct)
        return XPLMFlightLoopID(fl_id_int)

    def scheduleFlightLoop(
        self,
        loop_id: XPLMFlightLoopID,
        interval_seconds: float,
    ) -> None:
        if self.xp._runner is None:
            raise RuntimeError("FakeXP runner not initialized before scheduleFlightLoop")
        self.xp._runner.schedule_flightloop(int(loop_id), float(interval_seconds))

    def destroyFlightLoop(self, loop_id: XPLMFlightLoopID) -> None:
        if self.xp._runner is None:
            raise RuntimeError("FakeXP runner not initialized before destroyFlightLoop")
        self.xp._runner.destroy_flightloop(int(loop_id))
