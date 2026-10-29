"""Live hardware integration tests targeting connected Gamepower Icarus mouse.

Targets:
- Vendor interface probing at /dev/hidraw2 via find_vendor_node()
- Firmware PSD string verification: 0x56 0x39 0x30 0x31 ("V901")
- Active profile query (1 or 2)
- Profile 1 Config Block (Cmd 0x11) and Button Block (Cmd 0x12) reading
- Auto-backup persistence to ~/.local/state/icarusctl/
- Safe, non-destructive write, read-back verification, and full restoration

Skips gracefully if hardware is not connected or permissions are missing.
"""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path

from icarus.commands import STATE_DIR, ensure_backup
from icarus.config import RgbEffect, parse_config, serialize_config
from icarus.hidraw import DeviceNotFound, find_vendor_node
from icarus.protocol import (
    BLOCK_BUTTONS,
    BLOCK_CONFIG,
    EXPECTED_PSD,
    Device,
)


def _check_hardware_access() -> tuple[bool, str]:
    """Check whether the live mouse hardware is available and accessible."""
    try:
        node = find_vendor_node()
    except DeviceNotFound as exc:
        return False, f"Mouse hardware not found: {exc}"
    except Exception as exc:
        return False, f"Error scanning sysfs hidraw: {exc}"

    if not node.path.exists():
        return False, f"Device path {node.path} does not exist"

    if not os.access(node.path, os.R_OK | os.W_OK):
        return False, (
            f"Insufficient permissions on {node.path}. User requires rw access "
            "via 70-gamepower-icarus.rules"
        )

    return True, str(node.path)


HAS_HARDWARE, HARDWARE_REASON = _check_hardware_access()


@unittest.skipUnless(HAS_HARDWARE, f"Live hardware test skipped: {HARDWARE_REASON}")
class TestHardwareLive(unittest.TestCase):
    """Live hardware test suite running against connected mouse (/dev/hidraw2)."""

    def setUp(self) -> None:
        self.dev = Device.open()

    def tearDown(self) -> None:
        if hasattr(self, "dev") and hasattr(self.dev, "io") and hasattr(self.dev.io, "close"):
            self.dev.io.close()

    def test_probe_vendor_node(self) -> None:
        node = find_vendor_node()
        self.assertTrue(node.path.exists(), f"Path {node.path} does not exist")
        self.assertTrue(str(node.path).startswith("/dev/hidraw"))
        self.assertIn("0003:0000258A:00000027", node.hid_id.upper())

    def test_query_psd_string(self) -> None:
        raw_psd = self.dev.psd()
        self.assertEqual(
            raw_psd,
            EXPECTED_PSD,
            f"PSD mismatch: expected {EXPECTED_PSD.hex()} got {raw_psd.hex()}",
        )
        self.assertEqual(raw_psd, bytes([0x56, 0x39, 0x30, 0x31]))
        text_psd = self.dev.read_psd()
        self.assertEqual(text_psd, "V901")

    def test_query_active_profile(self) -> None:
        profile = self.dev.active_profile()
        self.assertIn(
            profile,
            (1, 2),
            f"Active profile must be 1 or 2, got {profile} (Profile 3 triggers STALL)",
        )

    def test_read_profile1_blocks(self) -> None:
        # Config block (Cmd 0x11)
        b1 = self.dev.read_block(1, BLOCK_CONFIG)
        self.assertEqual(len(b1), 520)
        self.assertEqual(b1[0], 0x04)
        self.assertEqual(b1[1], 0x11)

        cfg = parse_config(b1)
        self.assertEqual(cfg.profile, 1)
        self.assertEqual(len(cfg.dpi_stages), 8)
        self.assertIn(cfg.polling_rate, (125, 250, 500, 1000))

        # Button block (Cmd 0x12)
        b2 = self.dev.read_block(1, BLOCK_BUTTONS)
        self.assertEqual(len(b2), 520)
        self.assertEqual(b2[0], 0x04)
        self.assertEqual(b2[1], 0x12)

    def test_auto_backup_persists_to_state_dir(self) -> None:
        bak_dir = ensure_backup(self.dev)
        self.assertTrue(bak_dir.exists())
        self.assertTrue(
            str(bak_dir).startswith(str(STATE_DIR)),
            f"Backup dir {bak_dir} should be under {STATE_DIR}",
        )
        self.assertTrue(str(STATE_DIR).endswith("icarusctl"))

        for p in (1, 2):
            b1_file = bak_dir / f"p{p}_b1.bin"
            b2_file = bak_dir / f"p{p}_b2.bin"
            self.assertTrue(b1_file.exists(), f"Missing {b1_file}")
            self.assertTrue(b2_file.exists(), f"Missing {b2_file}")
            self.assertEqual(b1_file.stat().st_size, 520)
            self.assertEqual(b2_file.stat().st_size, 520)

    def test_safe_nondestructive_write_readback_restore(self) -> None:
        """Write safe speed parameter to Profile 1, verify read-back, and restore."""
        raw_orig = self.dev.read_block(1, BLOCK_CONFIG)
        cfg_orig = parse_config(raw_orig)
        orig_speed = cfg_orig.rgb_speed
        orig_effect = cfg_orig.rgb_effect

        test_speed = 3 if orig_speed == 2 else 2
        try:
            cfg_orig.rgb_effect = RgbEffect.STREAMING
            cfg_orig.rgb_speed = test_speed
            ser = serialize_config(cfg_orig)
            self.dev.write_block(bytes(ser))
            time.sleep(0.08)

            read_back_raw = self.dev.read_block(1, BLOCK_CONFIG)
            cfg_back = parse_config(read_back_raw)
            self.assertEqual(
                cfg_back.rgb_speed,
                test_speed,
                f"Write verification failed: expected speed {test_speed}, got {cfg_back.rgb_speed}",
            )
        finally:
            # Guarantee restoration of original hardware state
            cfg_orig.rgb_effect = orig_effect
            cfg_orig.rgb_speed = orig_speed
            restore_ser = serialize_config(cfg_orig)
            self.dev.write_block(bytes(restore_ser))
            time.sleep(0.12)

            restored_raw = self.dev.read_block(1, BLOCK_CONFIG)
            cfg_restored = parse_config(restored_raw)
            self.assertEqual(
                cfg_restored.rgb_speed,
                orig_speed,
                f"Restoration verification failed: expected speed {orig_speed}, got {cfg_restored.rgb_speed}",
            )


if __name__ == "__main__":
    unittest.main()
