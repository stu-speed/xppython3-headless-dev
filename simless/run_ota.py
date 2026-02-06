# ===========================================================================
# SIM-LESS OTA GUI HARNESS (XPWidget-based, multi-plugin aware)
# Allows user to set OAT interactively using FakeXPWidgets.
#
# See GUI_EMULATION.md for considerations in using GUI emulation
# ===========================================================================

import sys

import XPPython3
from simless.libs.fake_xp import FakeXP
from pathlib import Path


# Emulate plugin root dir
ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = ROOT / "plugins"
sys.path.insert(0, str(PLUGIN_ROOT))


def run_simless_ota_gui() -> None:
    xp = FakeXP(debug=True)
    XPPython3.xp = xp  # Replace X-Plane's xp API with FakeXP to run headless

    plugins = [
        "PI_sshd_OTA",
        "PI_sshd_dev_ota_gui",
    ]
    xp._run_plugin_lifecycle(plugins, debug=True, enable_gui=True)


if __name__ == "__main__":
    run_simless_ota_gui()
