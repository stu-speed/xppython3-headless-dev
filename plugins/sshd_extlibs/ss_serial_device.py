from __future__ import annotations

import time
from typing import Optional
import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo


class SerialDevice:
    def __init__(
        self,
        name: Optional[str] = None,
        serial_number: Optional[str] = None,
        baud_rate: int = 115200,
        conn_timeout: float = 0.05,
        retry_timeout: int = 60,
        ignore_dupe_msgs: bool = True,
    ):
        self.name = name
        self.serial_number = serial_number
        self.baud_rate = baud_rate
        self.timeout = conn_timeout
        self.retry_timeout = retry_timeout
        self.ignore_dupe_msgs = ignore_dupe_msgs

        self.conn: Optional[serial.Serial] = None
        self.last_retry: float
        self.prev_msg: str
        self._reset_vars()

    def _match_port(self, p: ListPortInfo) -> bool:
        if self.name is not None and p.name == self.name:
            return True
        if self.serial_number is not None and p.serial_number == self.serial_number:
            return True
        return False

    def _reset_vars(self) -> None:
        self.last_retry = 0
        self.prev_msg = ""

    def _format_msg(self, data: str, power_on=True) -> Optional[str]:
        msg = ""
        if power_on:
            msg = f"{data}\n"
        return msg

    def conn_ready(self) -> bool:
        if self.conn is not None:
            return True
        now = time.time()
        if now - self.last_retry < self.retry_timeout:
            return False
        self.last_retry = now

        try:
            for p in serial.tools.list_ports.comports():
                if self._match_port(p):
                    self.conn = serial.Serial(
                        p.device,
                        baudrate=self.baud_rate,
                        timeout=self.timeout,
                    )
                    break

            if self.conn is None:
                raise AttributeError(
                    f"Serial device {self.name or self.serial_number} not found"
                )
        except (AttributeError, OSError, serial.SerialException) as e:
            print(f"Failed to open serial port: {e}")
            return False

        return True

    def close_conn(self) -> None:
        if self.conn is None:
            return

        try:
            # send sleep command if applicable
            self.send_data("", power_on=False)
        except Exception:
            pass

        # ===========================================================================
        # Sequence to ensure com port is closed and released
        # ===========================================================================

        try:
            # flush buffers
            self.conn.reset_output_buffer()
            self.conn.reset_input_buffer()
        except Exception:
            pass

        try:
            # close underlying file descriptor explicitly
            if hasattr(self.conn, "fd") and self.conn.fd:
                try:
                    self.conn.fd.close()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            self.conn.close()
        except Exception:
            pass

        del self.conn  # ensure con is released
        self._reset_vars()

    def send_data(self, data: str, power_on=True) -> None:
        if not self.conn_ready():
            return
        assert self.conn is not None

        msg = self._format_msg(data, power_on)
        if self.ignore_dupe_msgs and msg == self.prev_msg:
            return

        try:
            self.conn.write(msg.encode("ascii"))
        except serial.SerialException as e:
            print(
                f"Failed to send data to device {self.name or self.serial_number}: {e}"
            )
            self._reset_vars()

        self.prev_msg = msg


class SerialOTA(SerialDevice):
    def _reset_vars(self) -> None:
        self.awake = False
        super()._reset_vars()

    def _format_msg(self, data: str, power_on: bool = True) -> Optional[str]:
        msg = ""
        if power_on:
            msg = f"{'W' if not self.awake else ''}{data}\n"
            self.awake = True
        elif self.awake:
            msg = "S\n"
            self.awake = False
        return msg
