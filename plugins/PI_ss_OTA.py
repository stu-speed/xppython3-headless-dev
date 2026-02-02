# ---------------------------------------------------------------------------
# OTA OAT Plugin
#
# Sends Outside Air Temperature (OAT) and avionics power state to a SerialOTA device
# ---------------------------------------------------------------------------

from typing import Any

from XPPython3 import xp

from .extensions.xp_interface import XPInterface
from .extensions.datarefs import DataRefSpec, DataRefRegistry, DataRefManager
from .extlibs.ss_serial_device import SerialOTA


# ===========================================================================
# DataRef specifications
# ===========================================================================

DATAREFS: dict[str, DataRefSpec] = {
    "oat_c": DataRefSpec(
        path="sim/cockpit2/temperature/outside_air_temp_degc",
        required=True,
        default=10.0,
    ),
    "avionics_on": DataRefSpec(
        path="sim/cockpit2/electrical/avionics_on",
        required=True,
        default=True,
    ),
}


# ===========================================================================
# Plugin class
# ===========================================================================

class PythonInterface:
    """
    XPPython3 plugin entry point.
    Manages device lifecycle, dataref readiness, and periodic updates.
    """

    Name: str
    Sig: str
    Desc: str

    xp: XPInterface
    device: SerialOTA | None
    floop: int | None

    registry: DataRefRegistry
    manager: DataRefManager

    def __init__(self) -> None:
        self.Name = "OTA display v1.0"
        self.Sig = "ota.speedsim.xppython3"
        self.Desc = "Display Outside Air Temp to serial device"

        self.xp = xp  # type: ignore[assignment]

        self.device = None
        self.floop = None

        self.registry = DataRefRegistry(self.xp, DATAREFS)
        self.manager = DataRefManager(self.registry, self.xp, timeout_seconds=30.0)

    def _ensure_device(self) -> bool:
        """Ensure the SerialOTA device is connected and ready."""
        if self.device is None:
            self.xp.log("OTA: creating SerialOTA device")
            self.device = SerialOTA(serial_number="F1TECH_ARCHER_OHP")

        if not self.device.conn_ready():
            self.xp.log("OTA: serial device unavailable")
            return False

        return True

    # ----------------------------------------------------------------------
    # Flight loop callback
    # ----------------------------------------------------------------------

    def flightloop_callback(
        self,
        since: float,
        elapsed: float,
        counter: int,
        refCon: Any,
    ) -> float:
        """Periodic callback to read datarefs and send values to the SerialOTA device."""

        if not self._ensure_device():
            return 10.0

        if not self.manager.ensure_datarefs():
            return 2.0

        temp_raw = self.registry["oat_c"].get()
        pwr_raw = self.registry["avionics_on"].get()

        tempc = float(temp_raw) if temp_raw is not None else 0.0
        avpwr = bool(pwr_raw)

        self.device.send_data(f"{int(tempc)}", power_on=avpwr)
        return 2.0

    # ----------------------------------------------------------------------
    # Plugin lifecycle
    # ----------------------------------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        self.xp.log("OTA: XPluginStart")
        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self) -> int | float:
        self.xp.log("OTA: XPluginEnable")

        if not self._ensure_device():
            return 0

        if not self.manager.ensure_datarefs():
            return 1.0  # retry later

        self.floop = self.xp.createFlightLoop(self.flightloop_callback)
        self.xp.scheduleFlightLoop(self.floop, -1)
        self.xp.log("OTA: flight loop scheduled")
        return 1

    def XPluginDisable(self) -> None:
        self.xp.log("OTA: XPluginDisable")

        if self.floop is not None:
            self.xp.destroyFlightLoop(self.floop)
            self.floop = None
            self.xp.log("OTA: flight loop destroyed")

        if self.device is not None:
            self.device.close_conn()
            self.device = None
            self.xp.log("OTA: serial device connection closed")

    def XPluginStop(self) -> None:
        self.xp.log("OTA: XPluginStop")
