from __future__ import annotations

from typing import Optional

from sshd_extensions.bridge_protocol import XPBridgeServer
from XPPython3 import xp
from XPPython3.xp_typing import XPLMFlightLoopID


class PythonInterface:
    """
    SSHD DataRef Bridge (thin shell)

    Responsibilities:
        • Instantiate XPBridgeServer (TCP, protocol, DataRefManager)
        • Register and schedule the flight loop
        • Tear down cleanly on disable/stop

    All protocol logic lives in XPBridgeServer.
    """

    Name: str
    Sig: str
    Desc: str

    _loop_id: Optional[XPLMFlightLoopID]
    _bridge: Optional[XPBridgeServer]

    def __init__(self) -> None:
        self.Name = "SSHD DataRef Bridge"
        self.Sig = "sshd.dataref.bridge"
        self.Desc = "Bridge managed datarefs to simless runner"

        self._loop_id = None
        self._bridge = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self) -> int:
        # Create protocol server bound to real xp.* interface
        self._bridge = XPBridgeServer(xp)

        # Register flight loop
        loop_id = xp.createFlightLoop(self._bridge.flightloop_cb)
        self._loop_id = loop_id

        # Schedule immediately; server controls its own pacing
        xp.scheduleFlightLoop(loop_id, -1.0)

        return 1

    def XPluginDisable(self) -> None:
        # Destroy flight loop if created
        if self._loop_id is not None:
            xp.destroyFlightLoop(self._loop_id)
            self._loop_id = None

        # Drop server reference (closes sockets + resets session)
        self._bridge = None

    def XPluginStop(self) -> None:
        # Nothing additional; disable handles teardown
        self._loop_id = None
        self._bridge = None
