# ===========================================================================
# SIM-LESS OTA GUI TEST HARNESS (XPWidget-based, multi-plugin aware)
# Allows user to set OAT datarefs interactively using FakeXPWidgets.
#
# See GUI_EMULATION.md for considerations in using GUI emulation
# ===========================================================================

from simless.libs.fake_xp import FakeXP


def run_simless_oat_gui() -> None:
    # log to terminal instead of log files for IDE debugging
    xp = FakeXP(terminal_logging=True)

    plugins = [
        "PI_sshd_OAT",
        "PI_sshd_oat_gui",
    ]

    xp.simless_runner.run_plugin_lifecycle(plugins)


if __name__ == "__main__":
    run_simless_oat_gui()
