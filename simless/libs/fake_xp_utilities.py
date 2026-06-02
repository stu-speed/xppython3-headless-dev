# simless/libs/fake_xp_utilities.py
# ===========================================================================
# FakeXPUtilities — XPUtilities-like subsystem for FakeXP
# ===========================================================================

from __future__ import annotations

import os
from pathlib import Path

class FakeXPUtilities:
    """
    Utility subsystem mixin for FakeXP.
    Provides XPUtilities-like helper functions.
    """

    def _init_utilities(self) -> None:
        # Stateless subsystem
        # Determine the simless "system path" once
        self._system_path = str(Path(__file__).resolve().parents[2])
        self._prefs_path = os.path.join(self._system_path, "Output", "preferences")

    # ------------------------------------------------------------------
    # SPEAK
    # ------------------------------------------------------------------
    def speakString(self, text: str) -> None:
        print(f"[FakeXP speak] {text}")

    # ------------------------------------------------------------------
    # PATHS
    # ------------------------------------------------------------------
    def getSystemPath(self) -> str:
        return self._system_path + os.sep

    def getPrefsPath(self) -> str:
        return self._prefs_path + os.sep

    def getDirectorySeparator(self) -> str:
        return os.sep
