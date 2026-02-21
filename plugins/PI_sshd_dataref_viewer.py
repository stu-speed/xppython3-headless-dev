from __future__ import annotations

from typing import Any

from XPPython3 import xp
from XPPython3.xp_typing import XPLMFlightLoopID

from sshd_extensions.xp_interface import XPInterface
from sshd_extensions.datarefs import DataRefManager

from sshd_extlibs.dataref_viewer import DataRefViewer


xp: XPInterface


class PythonInterface:
    Name: str
    Sig: str
    Desc: str

    manager: DataRefManager
    viewer: DataRefViewer
    floop: XPLMFlightLoopID | None

    def __init__(self) -> None:
        self.Name = "DataRef Viewer"
        self.Sig = "simless.datarefviewer"
        self.Desc = "Viewer for DataRefManager‑managed DataRefs"

        # Create DataRefManager exactly like OTA plugin
        self.manager = DataRefManager(
            xp,
            timeout_seconds=5.0,
        )

        # Viewer receives the manager explicitly
        self.viewer = DataRefViewer()

        self.floop = None

    # ----------------------------------------------------------------------
    # Flight loop callback
    # ----------------------------------------------------------------------

    def flightloop_callback(
        self,
        since: float,
        elapsed: float,
        counter: int,
        refcon: Any | None = None,
    ) -> float:

        # Wait for DataRefManager to be ready
        if not self.manager.ready(counter):
            return 0.5

        # Poll viewer (detect changes, redraw only when needed)
        self.viewer.poll()

        return 0.25

    # ----------------------------------------------------------------------
    # Plugin lifecycle
    # ----------------------------------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self) -> int:
        # Open viewer window automatically
        self.viewer.open()

        # Create + schedule flightloop
        self.floop = xp.createFlightLoop(self.flightloop_callback)
        xp.scheduleFlightLoop(self.floop, -1)

        return 1

    def XPluginDisable(self) -> None:
        # Close viewer window
        self.viewer.close()

        # Destroy flightloop
        if self.floop is not None:
            xp.destroyFlightLoop(self.floop)
            self.floop = None

    def XPluginStop(self) -> None:
        pass
