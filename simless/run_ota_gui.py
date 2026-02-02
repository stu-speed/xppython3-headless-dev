# ===========================================================================
# SIM-LESS OTA GUI HARNESS (XPWidget-based, multi-plugin aware)
# Allows user to set OAT interactively using FakeXPWidgets.
# ===========================================================================

import XPPython3
from simless.libs.fake_xp import FakeXP
from simless.libs.fake_xp_runner import FakeXPRunner


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------
def run_simless_ota_gui() -> None:
    # See GUI_EMULATION.md for considerations in using GUI emulation
    xp = FakeXP(debug=True)
    runner = FakeXPRunner(xp, enable_gui=True)

    # Replace X-Plane's xp module with FakeXP
    XPPython3.xp = xp

    # Load plugins through the runner (runner owns plugin loading)
    runner.load_plugin("plugins.PI_ss_OTA")
    runner.load_plugin("plugins.dev_ota_gui")

    # Execute full lifecycle (runner owns lifecycle + GUI)
    runner.run_plugin_lifecycle()


if __name__ == "__main__":
    run_simless_ota_gui()
