from __future__ import annotations

import os
from typing import Any


class FakeXPUtilities:
    """
    Miscellaneous utility functions to mimic X-Plane's XPUtilities API.
    """

    def speakString(self, text: str) -> None:
        """
        Simulate speaking a string.

        Currently implemented as a simple print; could be extended to use
        OS TTS facilities if desired.
        """
        print(f"[FakeXP speak] {text}")

    def getSystemPath(self) -> str:
        """
        Return a fake 'system path' for X-Plane.

        For testing, this is just the current working directory.
        """
        return os.getcwd()

    def getPrefsPath(self) -> str:
        """
        Return a fake preferences path.

        For testing, this is a 'prefs' directory under the current working directory.
        """
        return os.path.join(os.getcwd(), "prefs")

    def getDirectorySeparator(self) -> str:
        """Return the OS-specific directory separator."""
        return os.sep
