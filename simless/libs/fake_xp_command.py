# ===========================================================================
# FakeXPCommand — command subsystem mixin for FakeXP
#
# ROLE
#   Provide a minimal, deterministic, XPLM-style command façade for simless
#   execution. This subsystem owns the command registry and dispatches
#   command phases (begin/continue/end) to registered handlers exactly as
#   XPPython3 expects.
#
# API INVARIANTS
#   - Must match the observable behavior of XPLM command routing.
#   - Must not infer semantics or reinterpret plugin intent.
#   - Must not validate command paths against DataRefs (commands are actions,
#     not state).
#   - CommandRef objects must be opaque, hashable, and stable for the
#     lifetime of FakeXP.
#
# LIFETIME INVARIANTS
#   - Command registry is created during FakeXP construction and persists
#     for the entire simless session.
#   - Handlers may be registered at any time; dispatch must remain safe and
#     deterministic regardless of registration order.
#   - This subsystem is backend-agnostic: it never touches graphics, input,
#     or windowing systems.
#
# COMMAND MODEL
#   - Commands represent actions, not state.
#   - Each commandRef may have multiple handlers:
#         before-handlers  (before=1)
#         after-handlers   (before=0)
#   - Dispatch order is strictly:
#         all before-handlers → all after-handlers
#   - commandOnce() simulates a full press:
#         begin → continue → end
#
# PURPOSE
#   Provide a contributor-proof, deterministic command subsystem that
#   behaves like X-Plane’s XPLM command layer while remaining simple
#   enough for simless plugin testing.
# ===========================================================================

from __future__ import annotations

from typing import Callable, Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


# ---------------------------------------------------------------------------
# Opaque command reference (XPLM-style)
# ---------------------------------------------------------------------------

class FakeXPCommandRef:
    """Opaque, hashable command reference object."""

    def __init__(self, path: str) -> None:
        self.path = path

    def __repr__(self) -> str:
        return f"<FakeXPCommandRef {self.path}>"

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeXPCommandRef) and other.path == self.path


# ---------------------------------------------------------------------------
# FakeXPCommand mixin
# ---------------------------------------------------------------------------

class FakeXPCommand:
    """Command subsystem mixin for FakeXP."""

    xp: FakeXP

    # Internal registries
    _commands: Dict[str, FakeXPCommandRef]
    _handlers: Dict[FakeXPCommandRef, List[Tuple[Callable, int, object]]]

    # ----------------------------------------------------------------------
    # INITIALIZATION
    # ----------------------------------------------------------------------
    def _init_command(self) -> None:
        """Initialize command registry. Called by FakeXP during construction."""
        self._commands = {}
        self._handlers = {}

    # ----------------------------------------------------------------------
    # COMMAND CREATION / LOOKUP
    # ----------------------------------------------------------------------
    def createCommand(self, path: str, description: str) -> FakeXPCommandRef:
        """Create a new commandRef. Path does NOT need to correspond to a DataRef."""
        if path in self._commands:
            return self._commands[path]

        ref = FakeXPCommandRef(path)
        self._commands[path] = ref
        self._handlers[ref] = []
        return ref

    def findCommand(self, path: str) -> FakeXPCommandRef | None:
        """Return an existing commandRef or None."""
        return self._commands.get(path)

    # ----------------------------------------------------------------------
    # HANDLER REGISTRATION
    # ----------------------------------------------------------------------
    def registerCommandHandler(
        self,
        commandRef: FakeXPCommandRef,
        callback: Callable,
        before: int,
        refcon: object,
    ) -> None:
        """Register a command handler.

        before = 1 → before-handlers
        before = 0 → after-handlers
        """
        self._handlers[commandRef].append((callback, before, refcon))

    # ----------------------------------------------------------------------
    # DISPATCH
    # ----------------------------------------------------------------------
    def _dispatch(self, commandRef: FakeXPCommandRef, phase: int) -> None:
        """Dispatch a command phase to all registered handlers."""
        handlers = self._handlers.get(commandRef, [])

        # BEFORE handlers
        for cb, before, refcon in handlers:
            if before:
                cb(commandRef, phase, refcon)

        # AFTER handlers
        for cb, before, refcon in handlers:
            if not before:
                cb(commandRef, phase, refcon)

    # ----------------------------------------------------------------------
    # COMMAND EXECUTION
    # ----------------------------------------------------------------------
    def commandBegin(self, commandRef: FakeXPCommandRef) -> None:
        """Simulate a button press (phase 0)."""
        self._dispatch(commandRef, self.xp.CommandBegin)

    def commandEnd(self, commandRef: FakeXPCommandRef) -> None:
        """Simulate a button release (phase 2)."""
        self._dispatch(commandRef, self.xp.CommandEnd)

    def commandOnce(self, commandRef: FakeXPCommandRef) -> None:
        """Simulate a full press: begin → continue → end."""
        self.commandBegin(commandRef)
        self._dispatch(commandRef, self.xp.CommandContinue)
        self.commandEnd(commandRef)
