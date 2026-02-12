# simless/libs/fake_xp_flightloop.py
# ===========================================================================
# FakeXPFlightLoop — XP12-style flightloop struct factory for SimlessRunner
#
# Responsibilities:
#   • Create XP12-style flightloop “handles” (integer IDs)
#   • Store XP12-style struct metadata (callback, refcon, phase, etc.)
#   • Provide XP-facing API: create / destroy / schedule / unschedule / query
#   • Hold NO timing or scheduling state (SimlessRunner owns all scheduling)
#   • Expose raw structs so SimlessRunner can build its own scheduler entries
#
# IMPORTANT NOTE ABOUT SIGNATURES
#   XPPython3 (production) still uses the **legacy XP11-style callback
#   signature**:
#
#       float callback(float elapsedSinceLastCall,
#                      float elapsedTimeSinceLastFlightLoop,
#                      int   counter,
#                      void* refcon)
#
#   Simless, however, uses the **XP12-style struct-based API**, where
#   createFlightLoop() receives either:
#       • a struct dict containing callback/phase/refcon, or
#       • a bare callback function (convenience form)
#
#   FakeXPFlightLoop stores XP12-style structs so SimlessRunner can schedule
#   callbacks consistently, while still accepting the legacy callback form
#   for compatibility with XPPython3 plugins.
#
# Architectural invariants:
#   • This subsystem never infers timing or mutates runner state
#   • All scheduling calls are XP-facing no-ops
#   • getNextFlightLoopCallbackTime() returns runner-populated values only
#   • Structs are shallow-copied and never mutated after creation
# ===========================================================================

from __future__ import annotations
from typing import Any, Callable, Dict, Optional

from simless.libs.fake_xp_interface import FakeXPInterface


# XP12-style struct dictionary
FlightLoopStruct = Dict[str, Any]


class FakeXPFlightLoop:
    """
    XP12-style flight loop API façade.

    This subsystem:
      • Creates flightloop IDs and stores their XP12 struct metadata
      • Does NOT own any timing or scheduling
      • Exposes structs for an external runner (SimlessRunner) to consume
    """
    xp: FakeXPInterface  # established in FakeXP

    public_api_names = [
        "createFlightLoop",
        "destroyFlightLoop",
        "scheduleFlightLoop",
        "unscheduleFlightLoop",
        "getNextFlightLoopCallbackTime",
        "_get_flightloop_struct",
    ]

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

        # Runner-populated timing mirror: fid → next_call_time
        self._flightloop_times: Dict[int, float] = {}

    # ------------------------------------------------------------------
    # Runner-facing helper
    # ------------------------------------------------------------------
    def _get_flightloop_struct(self, fid: int) -> Optional[FlightLoopStruct]:
        """
        Fetch the XP12-style struct for a given flightloop ID.

        This is the ONLY entry point SimlessRunner uses to obtain callback,
        refcon, phase, and other metadata needed to build scheduler entries.
        """
        return self._flightloop_structs.get(fid)

    # ------------------------------------------------------------------
    # CREATE / DESTROY
    # ------------------------------------------------------------------
    def createFlightLoop(
        self,
        struct: FlightLoopStruct | Callable[..., float],
        refcon: Any = None,
    ) -> int:
        """
        XPPython3-compatible createFlightLoop.

        Accepts either:
          • A struct dict (XP12-style)
          • A bare callback function (legacy XP11-style convenience form)

        Returns:
          • Integer flightloop ID
        """
        # Legacy XP11-style: xp.createFlightLoop(callback)
        if callable(struct):
            struct = {
                "callback": struct,
                "phase": 0.0,
                "refcon": refcon,
            }

        fid = self._next_flightloop_id
        self._next_flightloop_id += 1

        # Store a shallow copy of the struct to avoid accidental mutation
        self._flightloop_structs[fid] = dict(struct)

        return fid

    def destroyFlightLoop(self, fid: int) -> None:
        """
        Remove struct metadata and any runner-populated timing mirror.
        """
        self._flightloop_structs.pop(fid, None)
        self._flightloop_times.pop(fid, None)

    # ------------------------------------------------------------------
    # SCHEDULING (XP-facing; runner owns real scheduling)
    # ------------------------------------------------------------------
    def scheduleFlightLoop(
        self,
        fid: int,
        interval: float,
        relativeToNow: int = 1,
    ) -> None:
        """
        XP-facing API. This subsystem performs NO scheduling.

        Expected behavior:
          • SimlessRunner intercepts this call (via xp.scheduleFlightLoop)
          • Runner uses _get_flightloop_struct(fid) to obtain metadata
          • Runner manages all timing, rescheduling, and execution

        This method intentionally performs no work.
        """
        pass

    def unscheduleFlightLoop(self, fid: int) -> None:
        """
        XP-facing API. Real unscheduling is performed by SimlessRunner.

        This method intentionally performs no work.
        """
        pass

    # ------------------------------------------------------------------
    # QUERY (optional timing view, populated by runner)
    # ------------------------------------------------------------------
    def getNextFlightLoopCallbackTime(self, fid: int) -> float:
        """
        XP-facing query.

        Returns:
          • Runner-populated next_call time
          • -1.0 if the runner has not populated timing for this ID

        SimlessRunner may mirror its internal scheduler state into
        self._flightloop_times[fid] to make this meaningful.
        """
        return self._flightloop_times.get(fid, -1.0)
