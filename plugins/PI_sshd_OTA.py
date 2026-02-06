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


def avionics_bus_volts(volts: list[float]) -> float:
    # No datarefs bound or array empty → avionics unpowered
    if not volts:
        return 0.0

    # Filter out obviously dead buses (< 1 volt)
    live = [(i, v) for i, v in enumerate(volts) if v > 1.0]

    # If nothing is alive, avionics are definitely unpowered
    if not live:
        return 0.0

    # Highest voltage on any bus (usually generator/alternator)
    max_v = max(v for _, v in live)

    # Identify A/B generator buses:
    # These are typically the highest-voltage buses in multi-engine aircraft.
    # We treat any bus within 0.3V of max_v as a generator bus.
    generator_buses = {
        i for i, v in live
        if abs(v - max_v) < 0.3
    }

    # Avionics buses are typically:
    #   • alive (>1V)
    #   • NOT one of the generator buses (A/B)
    #   • lower than the generator bus by a noticeable margin
    #   • stable (not a transient spike)
    avionics_candidates = [
        v for i, v in live
        if i not in generator_buses and v < max_v - 0.3
    ]

    # If we found a plausible avionics bus, return its voltage
    if avionics_candidates:
        # Choose the highest of the "lower" buses → most stable avionics feed
        return max(avionics_candidates)

    # If all live buses are equal (simple aircraft), return the first live bus
    return live[0][1]


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

        # Check device status or recovery on disconnects
        if not self._ensure_device():
            return 10.0

        temp_c = self.manager["oat_c"].get()
        volts_raw = self.manager["bus_volts"].get()

        try:
            volts_list = list(volts_raw) if volts_raw is not None else []
            av_volts = avionics_bus_volts(volts_list)
            avionic_on = float(av_volts) > 8.0
        except Exception as exc:
            xp.log(f"OTA: avionics bus detection error: {exc!r}")
            avionic_on = False

        self.device.send_data(f"{int(temp_c)}", power_on=avionic_on)
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
            xp.log("OTA: serial device not found")
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
