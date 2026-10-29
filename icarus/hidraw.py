"""Linux hidraw transport: sysfs discovery + feature-report ioctls (stdlib only)."""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from pathlib import Path

VENDOR_ID = 0x258A
PRODUCT_ID = 0x0027
# The vendor interface is the one whose report descriptor declares feature
# reports 0x04 (config block) and 0x05 (command). Matching on the descriptor
# instead of the interface number survives firmware revisions that reorder
# interfaces.
_CFG_REPORT_SIG = bytes([0x85, 0x04])
_CMD_REPORT_SIG = bytes([0x85, 0x05])

_IOC_RW = 3


def _ioc(nr: int, size: int) -> int:
    return (_IOC_RW << 30) | (size << 16) | (ord("H") << 8) | nr


def hidiocsfeature(size: int) -> int:
    return _ioc(0x06, size)


def hidiocgfeature(size: int) -> int:
    return _ioc(0x07, size)


class DeviceNotFound(RuntimeError):
    pass


DeviceNotFoundError = DeviceNotFound


@dataclass(frozen=True)
class HidrawNode:
    path: Path
    hid_id: str
    phys: str


def _parse_uevent(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, val = line.partition("=")
        if sep:
            out[key] = val
    return out


def find_vendor_node(sysfs: Path = Path("/sys/class/hidraw")) -> HidrawNode:
    """Return the hidraw node of the Icarus vendor (config) interface."""
    want = f"0003:{VENDOR_ID:08X}:{PRODUCT_ID:08X}"
    if not sysfs.is_dir():
        raise DeviceNotFound(f"{sysfs} missing (hidraw driver not loaded?)")
    for entry in sorted(sysfs.iterdir()):
        dev = entry / "device"
        try:
            ue = _parse_uevent((dev / "uevent").read_text())
            desc = (dev / "report_descriptor").read_bytes()
        except OSError:
            continue
        if ue.get("HID_ID", "").upper() != want:
            continue
        if _CFG_REPORT_SIG in desc and _CMD_REPORT_SIG in desc:
            return HidrawNode(Path("/dev") / entry.name, want, ue.get("HID_PHYS", ""))
    raise DeviceNotFound("Gamepower Icarus (258a:0027) vendor interface not found")


class Hidraw:
    """Owns one open /dev/hidraw* file descriptor."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self._fd = os.open(path, os.O_RDWR)
        except PermissionError as exc:
            raise PermissionError(
                f"{path}: permission denied. Install packaging/udev/70-gamepower-icarus.rules "
                "and replug the mouse."
            ) from exc

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def __enter__(self) -> "Hidraw":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def set_feature(self, data: bytes) -> None:
        buf = bytearray(data)
        fcntl.ioctl(self._fd, hidiocsfeature(len(buf)), buf, True)

    def get_feature(self, report_id: int, length: int) -> bytes:
        buf = bytearray(length)
        buf[0] = report_id
        n = fcntl.ioctl(self._fd, hidiocgfeature(length), buf, True)
        if n < 0:
            raise OSError(f"HIDIOCGFEATURE returned {n}")
        return bytes(buf[:n]) if n else bytes(buf)
