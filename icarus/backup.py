"""Pre-write state dumping and backup management for Gamepower Icarus."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from icarus.protocol import BLOCK_BUTTONS, BLOCK_CONFIG, Device

STATE_DIR = Path.home() / ".local" / "state" / "icarusctl"
ALT_STATE_DIR = Path.home() / ".local" / "state" / "icarus"


def ensure_backup(dev: Device) -> Path:
    """Ensure a full binary dump of both blocks across all profiles (1 and 2)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = STATE_DIR / f"backup_{ts}"
    for d in (STATE_DIR, ALT_STATE_DIR):
        (d / f"backup_{ts}").mkdir(parents=True, exist_ok=True)
    for p in (1, 2):
        b1 = dev.read_block(p, BLOCK_CONFIG)
        b2 = dev.read_block(p, BLOCK_BUTTONS)
        (out_dir / f"p{p}_b1.bin").write_bytes(b1)
        (out_dir / f"p{p}_b2.bin").write_bytes(b2)
        (ALT_STATE_DIR / f"backup_{ts}" / f"p{p}_b1.bin").write_bytes(b1)
        (ALT_STATE_DIR / f"backup_{ts}" / f"p{p}_b2.bin").write_bytes(b2)
    return out_dir


def verify_backup(backup_dir: Path) -> bool:
    """Verify that all 4 block files exist and are exactly 520 bytes."""
    if not backup_dir.is_dir():
        return False
    for p in (1, 2):
        b1 = backup_dir / f"p{p}_b1.bin"
        b2 = backup_dir / f"p{p}_b2.bin"
        if not b1.is_file() or b1.stat().st_size != 520:
            return False
        if not b2.is_file() or b2.stat().st_size != 520:
            return False
    return True


def restore_backup(dev: Device, backup_dir: Path) -> bool:
    """Restore configuration and button blocks from a verified backup directory."""
    if not verify_backup(backup_dir):
        return False
    for p in (1, 2):
        b1_file = backup_dir / f"p{p}_b1.bin"
        b2_file = backup_dir / f"p{p}_b2.bin"
        d1 = bytearray(b1_file.read_bytes())
        d1[3] = 0x7B  # config block write magic
        dev.write_block(bytes(d1))
        d2 = bytearray(b2_file.read_bytes())
        d2[3] = 0x50  # button block write magic
        dev.write_block(bytes(d2))
    return True
