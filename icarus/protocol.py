"""Sinowealth "8948" command protocol as used by OemDrv.exe (class CDrv8948).

Wire format (all HID feature reports on the vendor interface):
  report 0x05, 6 bytes : command  -> 05 c0 c1 c2 c3 c4
  report 0x04, 520 bytes: data block (config / buttons / macros)
Every write is retried 3x with 200 ms back-off, and the vendor app sleeps
20 ms (40 ms on some firmware) between a command and the matching read.
See SPEC.md for the per-command evidence addresses.
"""

from __future__ import annotations

import time
from typing import Protocol

REPORT_CMD = 0x05
REPORT_DATA = 0x04
CMD_LEN = 6
DATA_LEN = 520

CMD_GET_PSD = 0x01
CMD_PROFILE = 0x02
# Per-profile command bytes; high nibble = profile (1..3), low nibble = block.
BLOCK_CONFIG = 0x1
BLOCK_BUTTONS = 0x2
CONFIG_WRITE_MAGIC = 0x7B
PROFILES = (1, 2, 3)
EXPECTED_PSD = bytes([0x56, 0x39, 0x30, 0x31])  # Cfg.ini PSD=, ASCII "V901"

_CMD_DELAY_S = 0.04
_RETRIES = 3
_RETRY_DELAY_S = 0.2


class Transport(Protocol):
    def set_feature(self, data: bytes) -> None: ...
    def get_feature(self, report_id: int, length: int) -> bytes: ...


class ProtocolError(RuntimeError):
    pass


def block_cmd(profile: int, block: int) -> int:
    if profile not in PROFILES:
        raise ValueError(f"profile must be 1..3, got {profile}")
    return (profile << 4) | block


class Device:
    def __init__(self, io: Transport) -> None:
        self.io = io

    @classmethod
    def open(cls) -> Device:
        from icarus.hidraw import Hidraw, find_vendor_node
        node = find_vendor_node()
        h = Hidraw(node.path)
        return cls(h)

    def _retry_set(self, data: bytes) -> None:
        last: OSError | None = None
        for _ in range(_RETRIES):
            try:
                self.io.set_feature(data)
                return
            except OSError as exc:
                last = exc
                time.sleep(_RETRY_DELAY_S)
        raise ProtocolError(f"SetFeature report 0x{data[0]:02x} failed: {last}")

    def send_cmd(self, *args: int) -> None:
        payload = bytes(args)
        if len(payload) > CMD_LEN - 1:
            raise ValueError("command too long")
        self._retry_set(bytes([REPORT_CMD]) + payload.ljust(CMD_LEN - 1, b"\0"))

    def get_cmd(self, cmd: int) -> bytes:
        """Read the 4 reply bytes; the device echoes the command byte first."""
        time.sleep(_CMD_DELAY_S)
        r = self.io.get_feature(REPORT_CMD, CMD_LEN)
        if len(r) < CMD_LEN or r[1] != cmd:
            raise ProtocolError(f"command 0x{cmd:02x} reply mismatch: {r.hex(' ')}")
        return r[2:CMD_LEN]

    def psd(self) -> bytes:
        self.send_cmd(CMD_GET_PSD)
        return self.get_cmd(CMD_GET_PSD)

    def read_psd(self) -> str:
        return self.psd().decode("ascii", errors="replace").strip("\x00")

    def active_profile(self) -> int:
        self.send_cmd(CMD_PROFILE)
        p = self.get_cmd(CMD_PROFILE)[0]
        if p not in PROFILES:
            raise ProtocolError(f"device reported invalid profile {p}")
        return p

    def set_active_profile(self, profile: int) -> None:
        block_cmd(profile, 0)  # validates range
        # OemDrv passes the 0-based index and increments it before sending.
        self.send_cmd(CMD_PROFILE, profile)

    def read_block(self, profile: int, block: int) -> bytes:
        self.send_cmd(block_cmd(profile, block))
        time.sleep(_CMD_DELAY_S)
        data = self.io.get_feature(REPORT_DATA, DATA_LEN)
        # Firmware answers with a short report (141 B for config); the vendor
        # app works on a zero-padded 520 B buffer, so normalise to that.
        if not data or data[0] != REPORT_DATA or data[1] != block_cmd(profile, block):
            raise ProtocolError(f"bad data block: {data[:4].hex(' ')} len={len(data)}")
        return data.ljust(DATA_LEN, b"\0")

    def write_block(self, block_data: bytes) -> None:
        """Write a full 520-byte report-0x04 buffer (byte 0 must be 0x04)."""
        if len(block_data) != DATA_LEN or block_data[0] != REPORT_DATA:
            raise ValueError("write_block needs a 520-byte report 0x04 buffer")
        self._retry_set(block_data)
