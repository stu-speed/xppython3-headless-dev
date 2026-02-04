# ---------------------------------------------------------------------------
# OTA OAT Plugin
#
# Sends Outside Air Temperature (OAT) and avionics power state to a SerialOTA device
# ---------------------------------------------------------------------------

from __future__ import annotations

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
    # Use bus voltage array instead of a boolean avionics_on dataref
    "bus_volts": DataRefSpec(
        path="sim/cockpit2/electrical/bus_volts",
        required=True,
        default=[0.0, 0.0, 0.0, 0.0],
    ),
}


# ===========================================================================
# Helpers
# ===========================================================================

def detect_avionics_bus(volts: list[float]) -> int:
    """
    Heuristic to pick an avionics bus index from bus_volts.

    Strategy:
      - Find buses that are powered (> 1.0 V) but not the highest-voltage bus.
      - If exactly one candidate, use it.
      - If multiple, pick the first.
      - Fallback to index 1.
    """
    if not volts:
        return 1

    max_v = max(volts)

    candidates: list[int] = [
        i for i, v in enumerate(volts)
        if 1.0 < v < max_v - 0.5
    ]

    if len(candidates) == 1:
        return candidates[0]

    if candidates:
        return candidates[0]

    return 1


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
            return 5.0

        temp_raw = self.registry["oat_c"].get()
        volts_raw = self.registry["bus_volts"].get()

        tempc = float(temp_raw) if temp_raw is not None else 0.0

        try:
            volts_list = list(volts_raw) if volts_raw is not None else []
            idx = detect_avionics_bus(volts_list)
            avpwr = float(volts_list[idx]) > 1.0
        except Exception as exc:
            self.xp.log(f"OTA: avionics bus detection error: {exc!r}")
            avpwr = False

        self.device.send_data(f"{int(tempc)}", power_on=avpwr)
        return 2.0

    # ----------------------------------------------------------------------
    # Plugin lifecycle
    # ----------------------------------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        self.xp.log("OTA: XPluginStart")
        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self) -> int:
        self.xp.log("OTA: XPluginEnable")

        if not self._ensure_device():
            self.xp.log("OTA: serial device not found")
            return 0

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
            try:
                self.device.close_conn()
            except Exception as exc:
                self.xp.log(f"OTA: error closing serial device: {exc!r}")
            self.device = None
            self.xp.log("OTA: serial device connection closed")

    def XPluginStop(self) -> None:
        self.xp.log("OTA: XPluginStop")
