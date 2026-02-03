# ===========================================================================
# SIM-LESS OTA GUI HARNESS (XPWidget-based, multi-plugin aware)
# Allows user to set OAT interactively using FakeXPWidgets.
#
# See GUI_EMULATION.md for considerations in using GUI emulation
# ===========================================================================

import XPPython3
from simless.libs.fake_xp import FakeXP
from simless.libs.fake_xp_runner import FakeXPRunner


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------
def run_simless_ota_gui() -> None:
    xp = FakeXP(debug=True)
    # Replace X-Plane's xp module with FakeXP
    XPPython3.xp = xp

    # Execute full lifecycle (runner owns lifecycle + GUI)
    plugins = [
        "PI_ss_OTA",
        "dev_ota_gui",
    ]
    xp._run_plugin_lifecycle(plugins, debug=True, enable_gui=True)


if __name__ == "__main__":
    run_simless_ota_gui()
