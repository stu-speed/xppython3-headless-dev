# ===========================================================================
# SIM-LESS OTA GUI TEST HARNESS (XPWidget-based, multi-plugin aware)
# Allows user to set OAT datarefs interactively using FakeXPWidgets.
#
# See GUI_EMULATION.md for considerations in using GUI emulation
# ===========================================================================

from simless.libs.fake_xp import FakeXP


def run_gui_sample() -> None:
    xp = FakeXP(enable_gui=True)

    plugins = [
        "PI_sshd_gui_sample",
    ]

    xp.simless_runner.run_plugin_lifecycle(plugins)


if __name__ == "__main__":
    run_gui_sample()
