# ===========================================================================
# SIM-LESS OAT TEST HARNESS WITH LIVE DATAREFS
# Allows user to test OAT with live datarefs and monitor with viewer
#
# *REQUIRED: PL_sshd_dataref_bridge plugin running in X-plane
# ===========================================================================

from simless.libs.fake_xp import FakeXP


def run_simless_noaa() -> None:
    # log to terminal instead of log files for IDE debugging
    xp = FakeXP(terminal_logging=True)

    plugins = [
        "PI_noaaWeather",
    ]

    xp.simless_runner.run_plugin_lifecycle(plugins)


if __name__ == "__main__":
    run_simless_noaa()
