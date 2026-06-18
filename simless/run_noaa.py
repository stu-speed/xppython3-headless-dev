# ===========================================================================
# *REQUIRED: NOAA Weather Plugin install to framework PythonPlugins
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
