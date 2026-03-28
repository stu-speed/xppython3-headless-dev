# simless/libs/fake_xp_flightloop.py
# ===========================================================================
# FakeXPFlightLoop — XP12-style flightloop struct factory for SimlessRunner
# ===========================================================================

from __future__ import annotations

from typing import Any, Callable, cast, Dict, TYPE_CHECKING

from simless.libs.fake_xp_types import FlightLoopStruct
from XPPython3.xp_typing import XPLMFlightLoopPhaseType, XPLMFlightLoopID

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPFlightLoop:
    """
    XP12-style flight loop API façade.

    This subsystem:
      • Creates flightloop IDs and stores their XP12 struct metadata
      • Does NOT own any timing or scheduling
      • Exposes structs for an external runner (SimlessRunner) to consume
    """

    @property
    def fake_xp(self) -> FakeXP:
        return cast("FakeXP", cast(object, self))

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def _init_flightloop(self) -> None:
        """
        Initialize internal flightloop storage.

        FakeXPFlightLoop owns:
          • Struct metadata (callback, refcon, phase, structSize, etc.)
          • A read-only timing mirror (populated by SimlessRunner)
        """
        self._flightloop_structs: Dict[int, FlightLoopStruct] = {}
        self._next_flightloop_id: int = 1

    def getElapsedTime(self) -> float:
        """
            Return elapsed time since sim started.
        """
        return self.fake_xp.simless_runner._sim_time

    def getCycleNumber(self) -> int:
        """
            Get cycle number, increased for each cycle computed by sim.
        """
        return self.fake_xp.simless_runner._cycles

    def createFlightLoop(
        self,
        callback: Callable[[float, float, int, Any], float],
        phase: XPLMFlightLoopPhaseType = None,
        refCon: Any = None,
    ) -> XPLMFlightLoopID | int:
        """
        Create an XP12‑style flightloop struct with only the fields
        required by SimlessRunner.
        """
        if phase is None:
            phase = self.fake_xp.FlightLoop_Phase_BeforeFlightModel

        fid = self._next_flightloop_id
        self._next_flightloop_id += 1

        self._flightloop_structs[fid] = {
            "callback": callback,
            "refcon": refCon,
            "phase": phase,
            "interval": 0.0,  # default interval
            "next_call": 0.0,  # absolute sim time for next invocation
            "last_call": 0.0,  # absolute sim time of last invocation
            "counter": 0,  # number of times invoked
        }

        return fid

    def destroyFlightLoop(self, fid: int) -> None:
        """
        Remove struct metadata and any runner-populated timing mirror.
        """
        self._flightloop_structs.pop(fid, None)

    def scheduleFlightLoop(
        self,
        flightLoopID: XPLMFlightLoopID,
        interval: float = 0.0,
        relativeToNow: int = 1,
    ) -> None:
        """
        XP12‑style scheduling:
          • interval == 0 → stop
          • interval > 0 → seconds until next call
          • interval < 0 → N flightloops (runner interprets)
          • relativeToNow:
                1 → next_call = now + interval
                0 → next_call = last_call + interval
        """
        fl = self._flightloop_structs.get(flightLoopID)
        if fl is None:
            raise KeyError(f"Unknown FlightLoopID: {flightLoopID}")

        interval = float(interval)
        fl["interval"] = interval

        now = self.getElapsedTime()

        # Negative interval → runner interprets (XP12 behavior)
        if interval < 0:
            fl["next_call"] = now
            return

        # interval == 0 → stop
        if interval == 0:
            fl["next_call"] = float("inf")
            return

        # XP12 semantics for relativeToNow
        if relativeToNow:
            fl["next_call"] = now + interval
        else:
            fl["next_call"] = fl["last_call"] + interval

    def isFlightLoopValid(self, flightLoopID: XPLMFlightLoopID) -> bool:
        """
            Return True if flightLoopID exists and is valid: it may or may not be scheduled.
        """
        return flightLoopID in self._flightloop_structs

    def registerFlightLoopCallback(
        self, callback: Callable[[float, float, int, Any], float], interval: float = 0.0, refCon: Any = None
    ) -> None:
        raise RuntimeError("Old style registerFlightLoopCallback not supported")

    def unregisterFlightLoopCallback(
        self, callback: Callable[[float, float, int, Any], float], refCon: Any = None
    ) -> None:
        raise RuntimeError("Old style unregisterFlightLoopCallback not supported")

    def setFlightLoopCallbackInterval(
        self, callback: Callable[[float, float, int, Any], float], interval: float = 0.0, relativeToNow: int = 1,
        refCon: Any = None
    ) -> None:
        raise RuntimeError("Old style setFlightLoopCallbackInterval not supported")
