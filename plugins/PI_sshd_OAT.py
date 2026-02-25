# ---------------------------------------------------------------------------
# OTA OAT Plugin
#
# Sends Outside Air Temperature (OAT) and avionics power state to a SerialOTA device
# ---------------------------------------------------------------------------

from __future__ import annotations

from enum import Enum
from typing import Any, List

from XPPython3 import xp
from XPPython3.xp_typing import XPLMFlightLoopID

from sshd_extensions.xp_interface import XPInterface
from sshd_extensions.dataref_manager import DataRefManager
from sshd_extlibs.serial_device import SerialOAT


xp: XPInterface


class MDR(str, Enum):
    oat_c = "sim/cockpit2/temperature/outside_air_temp_degc"
    bus_volts = "sim/cockpit2/electrical/bus_volts"

# Default values used for simless testing
MANAGED_DATAREFS = {
    MDR.oat_c: { "required": True, "default": 10.0, },
    MDR.bus_volts: { "required": True, "default": [0.0] * 6, },
}


def avionics_bus_volts(volts: List[float]) -> float:
    if not volts:
        return 0.0

    live = [(i, v) for i, v in enumerate(volts) if v > 1.0]
    if not live:
        return 0.0

    max_v = max(v for _, v in live)

    generator_buses = {
        i for i, v in live
        if abs(v - max_v) < 0.3
    }

    avionics_candidates = [
        v for i, v in live
        if i not in generator_buses and v < max_v - 0.3
    ]

    if avionics_candidates:
        return max(avionics_candidates)

    return live[0][1]


class PythonInterface:
    Name: str
    Sig: str
    Desc: str

    manager: DataRefManager
    floop: XPLMFlightLoopID | None
    device: SerialOAT | None

    def __init__(self) -> None:
        self.Name = "OAT display v1.0"
        self.Sig = "oat.speedsim.xppython3"
        self.Desc = "Display Outside Air Temp to serial device"

        self.manager = DataRefManager(xp, MANAGED_DATAREFS, timeout_seconds=30.0)

        self.floop = None
        self.device = None

    def _ensure_device(self) -> bool:
        if self.device is None:
            xp.log("[OAT] creating SerialOTA device")
            self.device = SerialOAT(serial_number="F1TECH_ARCHER_OHP")

        if not self.device.conn_ready():
            xp.log("[OAT] serial device unavailable")
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
        # If managed datarefs, must always be at top of flightloop
        if not self.manager.ready():
            return 0.5  # required datarefs not available yet

        # Handle device reconnects
        if not self._ensure_device():
            return 10.0

        temp_c = self.manager.get_value(MDR.oat_c)
        volts_raw = self.manager.get_value(MDR.bus_volts)

        try:
            volts_list = list(volts_raw) if volts_raw is not None else []
            av_volts = avionics_bus_volts(volts_list)
            avionic_on = float(av_volts) > 8.0
        except Exception as exc:
            xp.log(f"[OAT] avionics bus detection error: {exc!r}")
            avionic_on = False

        self.device.send_data(f"{int(temp_c)}", power_on=avionic_on)
        return 1.0

    # ----------------------------------------------------------------------
    # Plugin lifecycle
    # ----------------------------------------------------------------------

    def XPluginStart(self) -> tuple[str, str, str]:
        return self.Name, self.Sig, self.Desc

    def XPluginEnable(self) -> int:
        if not self._ensure_device():
            xp.log("[OAT] serial device not found")
            if hasattr(xp, "simless_runner"):
                xp.log("[OAT] prime bridge datarefs for viewer anyway")
                self.manager.ready()
            return 0

        self.floop = xp.createFlightLoop(self.flightloop_callback)
        xp.scheduleFlightLoop(self.floop, -1)

        return 1

    def XPluginDisable(self) -> None:
        self.device.send_data(f"", power_on=False)

        if self.floop is not None:
            xp.destroyFlightLoop(self.floop)
            self.floop = None

    def XPluginStop(self) -> None:
        pass
