# simless/libs/fake_xp_flightloop.py
# ===========================================================================
# FakeXPFlightLoop — XP12-style flightloop struct factory for SimlessRunner
#
# Responsibilities:
#   • Create XP12-style flightloop "handles" and store their struct metadata
#   • Provide XP-facing API: create/destroy/schedule/unschedule/query
#   • Hold NO timing or scheduling state (runner owns all scheduling)
#   • Expose raw structs so SimlessRunner can build its own scheduler entries
# ===========================================================================

from __future__ import annotations
from typing import Any, Dict, Optional


class FakeXPFlightLoop:
    """
    XP12-style flight loop API façade.

    This subsystem:
      • Creates flightloop IDs and stores their XP12 struct metadata
      • Does NOT own any timing or scheduling
      • Exposes structs for an external runner (SimlessRunner) to consume
    """

    public_api_names = [
        "createFlightLoop",
        "destroyFlightLoop",
        "scheduleFlightLoop",
        "unscheduleFlightLoop",
        "getNextFlightLoopCallbackTime",
        "_get_flightloop_struct",
    ]

    def _init_flightloop(self) -> None:
        # ID → struct (XP12-style dict: callback, refcon, phase, structSize, etc.)
        self._flightloop_structs: Dict[int, Dict[str, Any]] = {}
        self._next_flightloop_id: int = 1

        # Optional: runner-populated timing view (read-only from xp side)
        # The runner can mirror its internal timing here if you want
        # getNextFlightLoopCallbackTime() to be meaningful.
        self._flightloop_times: Dict[int, float] = {}

    # ------------------------------------------------------------------
    # Internal helper for runner
    # ------------------------------------------------------------------
    def _get_flightloop_struct(self, fid: int) -> Optional[Dict[str, Any]]:
        """
        For SimlessRunner: fetch the XP12-style struct for a given flightloop ID.
        This is the ONLY place the runner needs to touch xp's flightloop state.
        """
        return self._flightloop_structs.get(fid)

    # ------------------------------------------------------------------
    # CREATE / DESTROY
    # ------------------------------------------------------------------
    def createFlightLoop(self, struct, refcon: Any = None) -> int:
        """
        XPPython3-compatible createFlightLoop:
        - Accepts either a struct dict or a bare callback function.
        """
        # Convenience form: xp.createFlightLoop(callback)
        if callable(struct):
            struct = {
                "callback": struct,
                "phase": 0.0,
                "refcon": refcon,
            }

        fid = self._next_flightloop_id
        self._next_flightloop_id += 1

        # Store a shallow copy of the struct
        self._flightloop_structs[fid] = dict(struct)

        return fid

    def destroyFlightLoop(self, fid: int) -> None:
        self._flightloop_structs.pop(fid, None)
        self._flightloop_times.pop(fid, None)

    # ------------------------------------------------------------------
    # SCHEDULING (XP-facing; runner owns real scheduling)
    # ------------------------------------------------------------------
    def scheduleFlightLoop(self, fid: int, interval: float, relativeToNow: int = 1) -> None:
        """
        XP-facing API. This does NOT schedule anything itself.

        The expectation is:
          • SimlessRunner intercepts this call (via xp.scheduleFlightLoop)
          • It then uses _get_flightloop_struct(fid) to obtain callback/refcon/etc.
          • It manages all timing and rescheduling internally.

        From FakeXPFlightLoop's perspective, this is a no-op.
        """
        # Intentionally no scheduling logic here.
        # You can optionally log/debug if desired:
        # self._dbg(f"scheduleFlightLoop(fid={fid}, interval={interval}, relativeToNow={relativeToNow})")
        pass

    def unscheduleFlightLoop(self, fid: int) -> None:
        """
        XP-facing API. Real unscheduling is done by the runner.

        This is a no-op here; the runner should handle unscheduling when it
        sees this call.
        """
        # self._dbg(f"unscheduleFlightLoop(fid={fid})")
        pass

    # ------------------------------------------------------------------
    # QUERY (optional timing view, populated by runner)
    # ------------------------------------------------------------------
    def getNextFlightLoopCallbackTime(self, fid: int) -> float:
        """
        XP-facing query. Returns -1.0 if the runner has not populated timing.

        If you want this to be meaningful, SimlessRunner can mirror its
        internal "next_call" time into self._flightloop_times[fid].
        """
        return self._flightloop_times.get(fid, -1.0)
