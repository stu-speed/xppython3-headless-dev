# simless/libs/fake_xp_utilities.py
# ===========================================================================
# FakeXPUtilities — XPUtilities-like subsystem for FakeXP
# ===========================================================================

from __future__ import annotations

import os


class FakeXPUtilities:
    """
    Utility subsystem mixin for FakeXP.
    Provides XPUtilities-like helper functions.
    """

    # Only include methods actually defined in this file
    public_api_names = [
        "speakString",
        "getSystemPath",
        "getPrefsPath",
        "getDirectorySeparator",
    ]

    def _init_utilities(self) -> None:
        # Stateless subsystem
        pass

    # ------------------------------------------------------------------
    # SPEAK
    # ------------------------------------------------------------------
    def speakString(self, text: str) -> None:
        print(f"[FakeXP speak] {text}")

    # ------------------------------------------------------------------
    # PATHS
    # ------------------------------------------------------------------
    def getSystemPath(self) -> str:
        return os.getcwd()

    def getPrefsPath(self) -> str:
        return os.path.join(os.getcwd(), "prefs")

    def getDirectorySeparator(self) -> str:
        return os.sep
