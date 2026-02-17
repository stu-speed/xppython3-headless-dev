from __future__ import annotations

from typing import Any

from XPPython3 import xp
from XPPython3.xp_typing import (
    XPLMFlightLoopID,
)

from sshd_extensions.bridge_protocol import (
    XPBridgeClient,
    BridgeMsgType,
    BRIDGE_PORT
)
from sshd_extlibs.dataref_viewer import viewer


LOG_PREFIX = "[BridgeViewer]"


def log(msg: str) -> None:
    xp.log(f"{LOG_PREFIX} {msg}")


class PythonInterface:
    Name: str
    Sig: str
    Desc: str

    client: XPBridgeClient | None
    floop: XPLMFlightLoopID | None

    def __init__(self) -> None:
        self.Name = "Bridge DataRef Viewer"
        self.Sig = "simless.bridge.viewer"
        self.Desc = "Displays DataRefs from bridge server"

        self.host = xp._bridge_host if hasattr(xp, "_bridge_host") else "127.0.0.1"
        self.port = BRIDGE_PORT
        self.paths = xp._bridge_paths if hasattr(xp, "_bridge_paths") else []

        self.client = None
        self.floop = None

        log(f"Initialized plugin with host={self.host}, port={self.port}, paths={self.paths}")

    # ----------------------------------------------------------------------
    # Flightloop callback
    # ----------------------------------------------------------------------

    def flightloop_callback(
        self,
        since: float,
        elapsed: float,
        counter: int,
        refcon: Any | None = None,
    ) -> float:

        # If client not connected yet, try once
        if self.client is None:
            log(f"Attempting connection to {self.host}:{self.port}")
            try:
                self.client = XPBridgeClient(host=self.host, port=self.port)
                self.client.connect()
                log("Connected to bridge")
                viewer.set_error(f"Connected to bridge {self.host}:{self.port}")

                log(f"Sending ADD for paths: {self.paths}")
                self.client.add(self.paths)

            except Exception as exc:
                log(f"Connection failed: {exc!r}")
                viewer.set_error(f"Bridge connect failed: {exc!r}")
                self.client = None
                return 2.0  # retry later

            return 0.1

        # Poll bridge
        try:
            msgs = self.client.poll()
        except Exception as exc:
            log(f"Bridge disconnected: {exc!r}")
            viewer.set_error(f"Bridge disconnected: {exc!r}")
            self.client = None
            return 2.0

        # Process messages
        for msg in msgs:
            t = msg.type
            v = msg.value

            if t is BridgeMsgType.META:
                viewer.update_meta(
                    idx=v.idx,
                    name=v.name,
                    type=v.type,
                    writable=v.writable,
                    array_size=v.array_size,
                )

            elif t is BridgeMsgType.UPDATE:
                for entry in v.entries:
                    viewer.update_value(entry.idx, entry.value)

            elif t is BridgeMsgType.ERROR:
                log(f"ERROR: {v.text}")
                viewer.set_error(v.text)

        return 0.05  # run at 20 Hz

    # ----------------------------------------------------------------------
    # Plugin lifecycle
    # ----------------------------------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        log("XPluginStart")
        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self) -> int:
        log("XPluginEnable")

        # Open viewer window
        viewer.open()
        log("Viewer window opened")

        # Create flightloop
        self.floop = xp.createFlightLoop(self.flightloop_callback)
        xp.scheduleFlightLoop(self.floop, -1.0)
        log("Flightloop scheduled")

        return 1

    def XPluginDisable(self) -> None:
        log("XPluginDisable")

        # Close viewer
        viewer.close()
        log("Viewer window closed")

        # Destroy flightloop
        if self.floop is not None:
            xp.destroyFlightLoop(self.floop)
            log("Flightloop destroyed")
            self.floop = None

        # Close bridge client
        if self.client is not None:
            try:
                self.client.disconnect()
                log("Bridge client disconnected")
            except Exception as exc:
                log(f"Error during disconnect: {exc!r}")
            self.client = None

    def XPluginStop(self) -> None:
        log("XPluginStop")
        pass
