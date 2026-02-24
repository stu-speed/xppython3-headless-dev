# ===========================================================================
# SIM-LESS OAT TEST HARNESS WITH LIVE DATAREFS
# Allows user to test OAT with live datarefs and monitor with viewer.
# ===========================================================================

import sys

import XPPython3

from simless.libs.fake_xp import FakeXP
from pathlib import Path


# Emulate plugin root dir
ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = ROOT / "plugins"
sys.path.insert(0, str(PLUGIN_ROOT))


def run_simless_oat_gui() -> None:
    xp = FakeXP(debug=True, enable_gui=True, enable_dataref_bridge=True)
    XPPython3.xp = xp

    plugins = [
        "PI_sshd_OAT",
        "PI_sshd_dataref_viewer",
    ]

    xp.run_plugin_lifecycle(plugins)


if __name__ == "__main__":
    run_simless_oat_gui()
