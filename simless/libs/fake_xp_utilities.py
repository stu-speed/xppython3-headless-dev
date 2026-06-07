# simless/libs/fake_xp_utilities.py
# ===========================================================================
# FakeXPUtilities — XPUtilities-like subsystem for FakeXP
# ===========================================================================

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING, cast

from XPPython3.xp_typing import XPLMCommandPhase, XPLMCommandRef
from simless.libs.fake_xp_types import CommandCallback, CommandHandlerRecord

if TYPE_CHECKING:
    from simless.libs.fake_xp import FakeXP


class FakeXPUtilities:
    """
    Utility subsystem mixin for FakeXP.
    Provides XPUtilities-like helper functions.
    """
    _next_command_idx: int
    _name_to_cmd: Dict[str, XPLMCommandRef]
    _cmd_to_name: Dict[XPLMCommandRef, str]
    _cmd_handlers: Dict[XPLMCommandRef, List[CommandHandlerRecord]]

    @property
    def fake_xp(self) -> FakeXP:
        return cast(FakeXP, cast(object, self))

    def _init_utilities(self) -> None:
        # Stateless subsystem
        self._next_command_idx = 1
        self._name_to_cmd = {}
        self._cmd_to_name = {}
        self._cmd_handlers = {}

    # ------------------------------------------------------------------
    # SPEAK
    # ------------------------------------------------------------------
    def speakString(self, text: str) -> None:
        print(f"[FakeXP speak] {text}")

    # ------------------------------------------------------------------
    # PATHS
    # ------------------------------------------------------------------
    def getSystemPath(self) -> str:
        return str(self.fake_xp._xplane_root) + os.sep

    def getPrefsPath(self) -> str:
        return os.path.join(self.fake_xp._xplane_root, "Output", "preferences")

    def getDirectorySeparator(self) -> str:
        return os.sep

    # ------------------------------------------------------------------
    # COMMANDS
    # ------------------------------------------------------------------

    def createCommand(self, name: str, description: Optional[str] = None) -> XPLMCommandRef:
        """
        xp.createCommand(name, description=None)

        Create or return an XPLMCommandRef for the given name.
        Does NOT attach behavior; you must register handlers separately.
        """
        if name in self._name_to_cmd:
            return self._name_to_cmd[name]

        cmd = XPLMCommandRef(self._next_command_idx)
        self._next_command_idx += 1

        self._name_to_cmd[name] = cmd
        self._cmd_to_name[cmd] = name
        self._cmd_handlers[cmd] = []

        # description is purely informational; you can store it if needed
        return cmd

    def findCommand(self, name: str) -> Optional[XPLMCommandRef]:
        """
        xp.findCommand(name) → XPLMCommandRef or None
        """
        return self._name_to_cmd.get(name)

    # -------- handler registration ------------------------------------

    def registerCommandHandler(
            self,
            commandRef: XPLMCommandRef,
            callback: CommandCallback,
            before: int = 1,
            refCon: Any = None,
    ) -> None:
        """
        xp.registerCommandHandler(commandRef, callback, before=1, refCon=None)
        """
        if commandRef not in self._cmd_handlers:
            self._cmd_handlers[commandRef] = []

        # XP allows same callback both before and after; we model flags explicitly
        rec = CommandHandlerRecord(
            callback=callback,
            refcon=refCon,
            before=bool(before),
            after=not bool(before),
        )
        self._cmd_handlers[commandRef].append(rec)

    def unregisterCommandHandler(
            self,
            commandRef: XPLMCommandRef,
            callback: CommandCallback,
            before: int,
            refCon: Any,
    ) -> None:
        """
        xp.unregisterCommandHandler(commandRef, callback, before, refCon)
        Parameters must match registration.
        """
        handlers = self._cmd_handlers.get(commandRef)
        if not handlers:
            return

        before_flag = bool(before)
        after_flag = not bool(before)

        self._cmd_handlers[commandRef] = [
            h for h in handlers
            if not (
                    h.callback is callback and
                    h.refcon is refCon and
                    h.before == before_flag and
                    h.after == after_flag
            )
        ]

    # -------- phase dispatch ------------------------------------------

    def _dispatch_phase(self, commandRef: XPLMCommandRef, phase: XPLMCommandPhase) -> None:
        handlers = self._cmd_handlers.get(commandRef, [])

        # BEFORE handlers
        for h in handlers:
            if h.before:
                if h.callback(commandRef, phase, h.refcon) == 0:
                    return  # stop further processing

        # NORMAL handlers (neither before nor after)
        for h in handlers:
            if not h.before and not h.after:
                if h.callback(commandRef, phase, h.refcon) == 0:
                    return  # stop further processing

        # AFTER handlers
        for h in handlers:
            if h.after:
                if h.callback(commandRef, phase, h.refcon) == 0:
                    return  # stop further processing

        # If no handler returned 0, XP internal behavior would run here
        # (FakeXP can optionally simulate built-in commands)

    # -------- public command API --------------------------------------

    def commandBegin(self, commandRef: XPLMCommandRef) -> None:
        """
        xp.commandBegin(commandRef)
        Generates CommandBegin then CommandContinue.
        """
        self._dispatch_phase(commandRef, self.fake_xp.CommandBegin)
        self._dispatch_phase(commandRef, self.fake_xp.CommandContinue)

    def commandEnd(self, commandRef: XPLMCommandRef) -> None:
        """
        xp.commandEnd(commandRef)
        Generates CommandEnd.
        """
        self._dispatch_phase(commandRef, self.fake_xp.CommandEnd)

    def commandOnce(self, commandRef: XPLMCommandRef) -> None:
        """
        xp.commandOnce(commandRef)
        Generates Begin → Continue → End.
        """
        self.commandBegin(commandRef)
        self.commandEnd(commandRef)
