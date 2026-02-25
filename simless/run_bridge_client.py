from __future__ import annotations

import time

import XPPython3

from sshd_extensions.bridge_protocol import XPBridgeClient, BRIDGE_HOST, BRIDGE_PORT
from simless.libs.fake_xp import FakeXP


DATAREF_PATHS = [
    "sim/cockpit2/temperature/outside_air_temp_degc",
    "sim/cockpit2/electrical/bus_volts"
]


def run_bridge_client() -> None:
    xp = FakeXP(debug=True, enable_gui=True, enable_dataref_bridge=True)
    XPPython3.xp = xp

    client = XPBridgeClient(xp, host=BRIDGE_HOST, port=BRIDGE_PORT)

    try:
        client.connect()

        # Register DataRefs
        print(f"[Client] ADD {DATAREF_PATHS}")
        client.add(DATAREF_PATHS)

    except Exception as exc:
        print(f"Connection failed: {exc!r}")
        return

    print("Waiting for messages...\n")

    try:
        while True:
            msgs = client.poll_data()
            for m in msgs:
                print(f"[Client] {m}")

            time.sleep(0.05)

    except ConnectionResetError as exc:
        print(f"Disconnected from bridge: {exc}")

    except KeyboardInterrupt:
        print("Interrupted by user")

    finally:
        client.disconnect()
        print("Client closed")


if __name__ == "__main__":
    run_bridge_client()