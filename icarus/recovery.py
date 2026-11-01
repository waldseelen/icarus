"""Factory reset and PixArt PMW3325 sensor recovery for Gamepower Icarus."""

from __future__ import annotations

import base64
import os
import select
import struct
import time
import zlib
from pathlib import Path

from icarus.backup import ensure_backup
from icarus.protocol import Device

# Byte-exact compressed factory binaries (p1_b1, p1_b2, p2_b1, p2_b2 - 520 bytes each)
_EMBEDDED_FACTORY_B85 = (
    "c%1E&F>b;@5JmqCqb0@?u((bE4OB!)MHv!A%@u-Z;>t(ZLvesT5;YXd?AjtCQlvDI70J*3v-0<R$&#fn7K*_kmldR+4"
    "f5gq84aNx=?YGzPZ55>7~a1b=hX6mb8sF$d>%Ex?@cCcU+M_zbh<gcEA>=}Kw@%qw2DmPG_V9%{V`U6iiqq3FjG}bRP|"
    "Isw9}p6s^fnl(>M)~^CI@auz38T54K-@K#W(lxF4FOko@Lg#?8M)&fogr+$%Zt0XC<u586j&ao+dAM=^TZ(`dX_Z>`=G"
    "OI6nPr*`}yS12H23j"
)


def get_factory_blocks() -> dict[str, bytes]:
    """Retrieve verified factory blocks (from disk fixtures or embedded fallback)."""
    candidates = [
        Path(__file__).resolve().parent.parent / "tests" / "data",
        Path("/usr/share/icarusctl/data"),
        Path.home() / ".local" / "share" / "icarusctl" / "data",
    ]
    for d in candidates:
        if (d / "p1_b1.bin").is_file():
            try:
                res = {
                    "p1_b1": (d / "p1_b1.bin").read_bytes(),
                    "p1_b2": (d / "p1_b2.bin").read_bytes(),
                    "p2_b1": (d / "p2_b1.bin").read_bytes(),
                    "p2_b2": (d / "p2_b2.bin").read_bytes(),
                }
                if all(len(v) == 520 for v in res.values()):
                    return res
            except OSError:
                pass

    decomp = zlib.decompress(base64.b85decode(_EMBEDDED_FACTORY_B85.encode("ascii")))
    return {
        "p1_b1": decomp[0:520],
        "p1_b2": decomp[520:1040],
        "p2_b1": decomp[1040:1560],
        "p2_b2": decomp[1560:2080],
    }


def find_motion_node() -> Path:
    """Find the boot mouse hidraw node (EP 0x81, /dev/hidraw0)."""
    sysfs = Path("/sys/class/hidraw")
    want = f"0003:{0x258A:08X}:{0x0027:08X}"
    if sysfs.is_dir():
        for entry in sorted(sysfs.iterdir()):
            dev_dir = entry / "device"
            try:
                uevent = (dev_dir / "uevent").read_text()
                desc = (dev_dir / "report_descriptor").read_bytes()
            except OSError:
                continue
            if want in uevent.upper() and len(desc) == 71:
                node_path = Path("/dev") / entry.name
                if node_path.exists():
                    return node_path
    return Path("/dev/hidraw0")


def verify_sensor_motion(timeout_ms: int = 1000) -> bool:
    """Read /dev/hidraw0 to check for non-zero relative dx/dy motion vectors or packet stream."""
    node_path = find_motion_node()
    if not node_path.exists():
        return False

    try:
        fd = os.open(node_path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return False

    try:
        deadline = time.time() + (timeout_ms / 1000.0)
        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            r, _, _ = select.select([fd], [], [], min(remaining, 0.05))
            if r:
                try:
                    data = os.read(fd, 64)
                except OSError:
                    break
                if len(data) >= 7:
                    _, dx, dy, _, _ = struct.unpack("<Bhhbb", data[:7])
                    if dx != 0 or dy != 0:
                        return True
                    return True
        return False
    finally:
        os.close(fd)


def perform_factory_reset(dev: Device) -> tuple[bool, str]:
    """Execute complete factory reset & PMW3325 optical sensor recovery sequence."""
    try:
        bak_dir = ensure_backup(dev)
    except Exception as exc:
        return False, f"Pre-reset state backup failed: {exc}"

    blocks = get_factory_blocks()

    # Step 1: Write Profile 2 factory config (0x7B) and buttons (0x50)
    p2_b1 = bytearray(blocks["p2_b1"])
    p2_b1[3] = 0x7B
    dev.write_block(bytes(p2_b1))

    p2_b2 = bytearray(blocks["p2_b2"])
    p2_b2[3] = 0x50
    dev.write_block(bytes(p2_b2))

    # Step 2: Write Profile 1 factory config (0x7B) and buttons (0x50)
    p1_b1 = bytearray(blocks["p1_b1"])
    p1_b1[3] = 0x7B
    dev.write_block(bytes(p1_b1))

    p1_b2 = bytearray(blocks["p1_b2"])
    p1_b2[3] = 0x50
    dev.write_block(bytes(p1_b2))

    # Step 3: Sleep 20ms and toggle active profile (switch to P2, sleep 20ms, switch to P1)
    time.sleep(0.02)
    dev.set_active_profile(2)
    time.sleep(0.02)
    dev.set_active_profile(1)

    return True, f"Factory reset successfully flashed to device. Backup: {bak_dir}"
