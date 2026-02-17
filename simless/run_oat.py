# ===========================================================================
# SIM-LESS OTA GUI HARNESS (XPWidget-based, multi-plugin aware)
# Allows user to set OAT interactively using FakeXPWidgets.
#
# See GUI_EMULATION.md for considerations in using GUI emulation
# ===========================================================================

import sys
from enum import Enum

import XPPython3
from simless.libs.fake_xp import FakeXP
from pathlib import Path


BRIDGE_HOST = "10.22.50.189"

# Emulate plugin root dir
ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = ROOT / "plugins"
sys.path.insert(0, str(PLUGIN_ROOT))

class MDR(str, Enum):
    oat_c = "sim/cockpit2/temperature/outside_air_temp_degc"
    bus_volts = "sim/cockpit2/electrical/bus_volts"


def run_simless_oat_gui() -> None:
    xp = FakeXP(debug=True, enable_gui=True)
    XPPython3.xp = xp

    xp._bridge_host = BRIDGE_HOST
    xp._bridge_paths = [MDR.oat_c, MDR.bus_volts]

    plugins = [
        "PI_sshd_OAT",
        "PI_sshd_dev_oat_gui",
        "PI_sshd_dataref_viewer"
    ]

    xp.run_plugin_lifecycle(plugins)


if __name__ == "__main__":
    run_simless_oat_gui()
