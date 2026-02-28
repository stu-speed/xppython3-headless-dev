# ===========================================================================
# SIM-LESS OAT TEST HARNESS WITH LIVE DATAREFS
# Allows user to test OAT with live datarefs and monitor with viewer
#
# *REQUIRED: PL_sshd_dataref_bridge plugin running in X-plane
# ===========================================================================

import sys
from pathlib import Path

import XPPython3
from simless.libs.fake_xp import FakeXP
from sshd_extensions.bridge_protocol import BRIDGE_HOST, BRIDGE_PORT

# Emulate plugin root dir
ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = ROOT / "plugins"
sys.path.insert(0, str(PLUGIN_ROOT))


def run_simless_oat_gui() -> None:
    xp = FakeXP(
        debug=True, enable_gui=True, enable_dataref_bridge=True, bridge_host=BRIDGE_HOST,
        bridge_port=BRIDGE_PORT
    )
    XPPython3.xp = xp

    plugins = [
        "PI_sshd_OAT",
    ]

    xp.simless_runner.run_plugin_lifecycle(plugins, enable_dataref_viewer=True)


if __name__ == "__main__":
    run_simless_oat_gui()
