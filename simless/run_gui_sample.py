# ===========================================================================
# SIM-LESS OTA GUI TEST HARNESS (XPWidget-based, multi-plugin aware)
# Allows user to set OAT datarefs interactively using FakeXPWidgets.
#
# See GUI_EMULATION.md for considerations in using GUI emulation
# ===========================================================================

import sys
from pathlib import Path

import XPPython3
from simless.libs.fake_xp import FakeXP

# Emulate plugin root dir
ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = ROOT / "plugins"
sys.path.insert(0, str(PLUGIN_ROOT))


def run_gui_sample() -> None:
    xp = FakeXP(debug=True, enable_gui=True)
    XPPython3.xp = xp

    plugins = [
        "PI_sshd_gui_sample",
    ]

    xp.simless_runner.run_plugin_lifecycle(plugins)


if __name__ == "__main__":
    run_gui_sample()
