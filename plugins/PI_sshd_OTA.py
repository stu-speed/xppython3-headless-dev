# ---------------------------------------------------------------------------
# OTA OAT Plugin
#
# Sends Outside Air Temperature (OAT) and avionics power state to a SerialOTA device
# ---------------------------------------------------------------------------
from typing import Any

from XPPython3 import xp

from sshd_extensions.datarefs import DataRefSpec, DRefType, DataRefManager
from sshd_extlibs.ss_serial_device import SerialOTA


# ===========================================================================
# Managed DataRef specifications
# ===========================================================================

DATAREFS: dict[str, DataRefSpec] = {
    "oat_c": DataRefSpec(
        path="sim/cockpit2/temperature/outside_air_temp_degc",
        dtype=DRefType.FLOAT,
        writable=True,
        required=True,
        default=10.0,
    ),
    "bus_volts": DataRefSpec(
        path="sim/cockpit2/electrical/bus_volts",
        dtype=DRefType.FLOAT_ARRAY,
        writable=True,
        required=True,
        default=[0.0] * 6,
    ),
}


# ===========================================================================
# Helpers
# ===========================================================================

def detect_avionics_bus(volts: list[float]) -> int:
    if not volts:
        return 1

    max_v = max(volts)
    candidates = [i for i, v in enumerate(volts) if 1.0 < v < max_v - 0.5]

    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return candidates[0]
    return 1


class PythonInterface:

    Name: str
    Sig: str
    Desc: str
    manager: DataRefManager
    floop: Any | None
    device: SerialOTA | None

    def __init__(self) -> None:
        self.Name = "OTA display v1.0"
        self.Sig = "ota.speedsim.xppython3"
        self.Desc = "Display Outside Air Temp to serial device"
        self.manager = DataRefManager(DATAREFS, xp, timeout_seconds=30.0)
        self.floop = None
        self.device = None

    def _ensure_device(self) -> bool:
        """Ensure the SerialOTA device is connected and ready."""
        if self.device is None:
            xp.log("OTA: creating SerialOTA device")
            self.device = SerialOTA(serial_number="F1TECH_ARCHER_OHP")

        if not self.device.conn_ready():
            xp.log("OTA: serial device unavailable")
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
        refcon: Any | None = None,
    ) -> float:
        """Periodic callback to read datarefs and send values to the SerialOTA device."""

        # Managed datarefs must check for readiness before they can be referenced
        if not self.manager.ready(counter):
            return 0.5

        # Handle device recovery on disconnects
        if not self._ensure_device():
            return 10.0

        temp_raw = self.manager["oat_c"].get()
        volts_raw = self.manager["bus_volts"].get()

        try:
            volts_list = list(volts_raw) if volts_raw is not None else []
            idx = detect_avionics_bus(volts_list)
            avpwr = float(volts_list[idx]) > 8.0
        except Exception as exc:
            xp.log(f"OTA: avionics bus detection error: {exc!r}")
            avpwr = False

        xp.log(f"OTA: temp:{int(temp_raw)} volts:{volts_raw} avionics:{avpwr}")
        return 2.0

    # ----------------------------------------------------------------------
    # Plugin lifecycle
    # ----------------------------------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        xp.log("OTA: XPluginStart")
        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self) -> int:
        xp.log("OTA: XPluginEnable")

        if not self._ensure_device():
            self.xp.log("OTA: serial device not found")
            return 0

        self.floop = xp.createFlightLoop(self.flightloop_callback)
        xp.scheduleFlightLoop(self.floop, -1)

        xp.log("OTA: flight loop scheduled")
        return 1

    def XPluginDisable(self) -> None:
        xp.log("OTA: XPluginDisable")

        if self.floop is not None:
            xp.destroyFlightLoop(self.floop)
            self.floop = None
            xp.log("OTA: flight loop destroyed")

        if self.device is not None:
            try:
                self.device.close_conn()
            except Exception as exc:
                xp.log(f"OTA: error closing serial device: {exc!r}")
            self.device = None
            xp.log("OTA: serial device connection closed")

    def XPluginStop(self) -> None:
        xp.log("OTA: XPluginStop")
