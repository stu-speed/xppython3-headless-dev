from __future__ import annotations

import time

from sshd_extensions.xp_bridge_protocol import XPBridgeClient, BridgeMessage
from simless.libs.constants import BRIDGE_HOST, BRIDGE_PORT


DATAREF_PATHS = [
    "sim/cockpit2/temperature/outside_air_temp_degc",
]


def run_bridge_client() -> None:
    print("=== Simless Bridge Client ===")
    print(f"Connecting to bridge at {BRIDGE_HOST}:{BRIDGE_PORT}")

    client = XPBridgeClient(host=BRIDGE_HOST, port=BRIDGE_PORT)

    try:
        client.connect()
        print("Connected")

        # Register DataRefs
        for path in DATAREF_PATHS:
            print(f"[Client] ADD {path}")
            client.add(path)

    except Exception as exc:
        print(f"Connection failed: {exc!r}")
        return

    print("Waiting for messages...\n")

    try:
        while True:
            msg = client.poll()
            if msg is None:
                continue
            print(f"[Client] {msg}")

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
