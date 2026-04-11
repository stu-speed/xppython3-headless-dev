from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class FlightLoop:
    """
    XP12‑style flightloop scheduling capsule.
    """

    # Immutable identity fields
    callback: Callable[[float, float, int, Any], float]
    refcon: Any
    phase: int
    plugin_id: int

    # Mutable scheduling state
    interval: float = 0.0
    next_call: float = float("inf")
    next_cycle: Optional[int] = None

    # Mutable runtime state
    last_call: float = 0.0
    last_cycle: int = 0
    counter: int = 0

    # ------------------------------------------------------------------
    # Public API #1: schedule()
    # ------------------------------------------------------------------
    def schedule(
        self,
        interval: float,
        relative_to_now: bool,
        now: float,
        cycle: int,
    ) -> None:

        interval = float(interval)
        self.interval = interval

        # Stop
        if interval == 0:
            self.next_call = float("inf")
            self.next_cycle = None
            return

        # Cycle-based scheduling
        if interval < 0:
            N = abs(int(interval))
            if relative_to_now:
                self.next_cycle = cycle + N
            else:
                self.next_cycle = self.last_cycle + N

            self.next_call = float("inf")
            return

        # Time-based scheduling
        if relative_to_now:
            self.next_call = now + interval
        else:
            self.next_call = self.last_call + interval

        self.next_cycle = None

    # ------------------------------------------------------------------
    # Public API #2: check_and_run()
    # ------------------------------------------------------------------
    def check_and_run(self, now: float, cycle: int) -> None:
        """
        Called once per frame by the runner.
        If interval == 0, the loop is inactive and does nothing.
        """

        # Inactive
        if self.interval == 0:
            return

        # Determine readiness
        ready = False

        if self.interval < 0:
            # Cycle-based
            if self.next_cycle is not None and cycle >= self.next_cycle:
                ready = True
        else:
            # Time-based
            if now >= self.next_call:
                ready = True

        if not ready:
            return

        # Callback must exist
        if self.callback is None:
            raise RuntimeError("FlightLoop is ready to run but no callback is set")

        # Compute callback args
        since = now - self.last_call
        elapsed = since
        counter = self.counter

        # Run callback — bubble exceptions to runner
        next_interval = self.callback(since, elapsed, counter, self.refcon)

        # Update last-call state
        self.last_call = now
        self.last_cycle = cycle
        self.counter += 1

        # XP semantics: None or <0 → reuse previous interval
        if next_interval is None or next_interval < 0:
            next_interval = self.interval

        # Store new interval
        self.interval = float(next_interval)

        # interval == 0 → stop
        if next_interval == 0:
            self.next_call = float("inf")
            self.next_cycle = None
            return

        # Reschedule
        if next_interval < 0:
            N = abs(int(next_interval))
            self.next_cycle = cycle + N
            self.next_call = float("inf")
        else:
            self.next_call = now + float(next_interval)
            self.next_cycle = None
