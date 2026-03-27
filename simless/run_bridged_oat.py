# ===========================================================================
# SIM-LESS OAT TEST HARNESS WITH LIVE DATAREFS
# Allows user to test OAT with live datarefs and monitor with viewer
#
# *REQUIRED: PL_sshd_dataref_bridge plugin running in X-plane
# ===========================================================================

from simless.libs.fake_xp import FakeXP


def run_simless_oat_gui() -> None:
    xp = FakeXP(
        enable_gui=True, enable_dataref_bridge=True
    )

    plugins = [
        "PI_sshd_OAT",
    ]

    xp.simless_runner.run_plugin_lifecycle(plugins, enable_dataref_viewer=True)


if __name__ == "__main__":
    run_simless_oat_gui()
