from __future__ import annotations

import time

from sshd_extensions.bridge_protocol import (
    XPBridgeClient,
    BridgeMsgType,
    BRIDGE_PORT
)


BRIDGE_HOST = "10.22.50.189"

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

        # Register DataRefs (list-based ADD)
        print(f"[Client] ADD {DATAREF_PATHS}")
        client.add(DATAREF_PATHS)

    except Exception as exc:
        print(f"Connection failed: {exc!r}")
        return

    print("Waiting for messages...\n")

    try:
        while True:
            msgs = client.poll()   # always returns a list (possibly empty)
            for msg in msgs:
                print(msg.to_dict())

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
