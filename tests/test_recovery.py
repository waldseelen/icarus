"""Unit tests for factory reset and sensor recovery logic."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from icarus.protocol import BLOCK_BUTTONS, BLOCK_CONFIG, Device
from icarus.recovery import (
    _EMBEDDED_FACTORY_B85,
    find_motion_node,
    get_factory_blocks,
    perform_factory_reset,
    verify_sensor_motion,
)

DATA_DIR = Path(__file__).resolve().parent / "data"


class MockTransport:
    def __init__(self) -> None:
        self.feature_reports: dict[int, bytes] = {}
        self.sent_feature_reports: list[bytes] = []

    def get_feature_report(self, report_id: int, size: int) -> bytes:
        return self.feature_reports.get(report_id, bytes(size))

    def send_feature_report(self, data: bytes) -> int:
        self.sent_feature_reports.append(data)
        return len(data)

    def close(self) -> None:
        pass


class MockRecoveryDevice(Device):
    """Mock Device that records write_block and set_active_profile calls."""

    def __init__(self) -> None:
        super().__init__(MockTransport())  # type: ignore[arg-type]
        self.written_blocks: list[bytes] = []
        self.profile_switches: list[int] = []
        self.active_prof: int = 1

    def read_block(self, profile: int, block_type: int) -> bytes:
        return bytes([0x04, (profile << 4) | (0x01 if block_type == BLOCK_CONFIG else 0x02), 0x00, 0x00] + [0xEE] * 516)

    def write_block(self, data: bytes) -> None:
        self.written_blocks.append(data)

    def set_active_profile(self, profile: int) -> None:
        self.profile_switches.append(profile)
        self.active_prof = profile

    def active_profile(self) -> int:
        return self.active_prof


class TestRecovery(unittest.TestCase):
    """Test suite for icarus.recovery module."""

    def test_get_factory_blocks_structure_and_lengths(self) -> None:
        blocks = get_factory_blocks()
        expected_keys = {"p1_b1", "p1_b2", "p2_b1", "p2_b2"}
        self.assertEqual(set(blocks.keys()), expected_keys)

        for name, data in blocks.items():
            self.assertEqual(len(data), 520, f"Block {name} must be 520 bytes, got {len(data)}")
            self.assertEqual(data[0], 0x04, f"Block {name} Report ID must be 0x04")

        # Verify command IDs in byte 1
        self.assertEqual(blocks["p1_b1"][1], 0x11, "Profile 1 Config block command must be 0x11")
        self.assertEqual(blocks["p1_b2"][1], 0x12, "Profile 1 Button block command must be 0x12")
        self.assertEqual(blocks["p2_b1"][1], 0x21, "Profile 2 Config block command must be 0x21")
        self.assertEqual(blocks["p2_b2"][1], 0x22, "Profile 2 Button block command must be 0x22")

    def test_get_factory_blocks_calibration_bytes(self) -> None:
        """Verify PMW3325 calibration offsets (104..128, 130..131) in factory blocks."""
        blocks = get_factory_blocks()

        if (DATA_DIR / "p1_b1.bin").is_file():
            fixture_p1_b1 = (DATA_DIR / "p1_b1.bin").read_bytes()
            for off in range(104, 129):
                self.assertEqual(
                    blocks["p1_b1"][off],
                    fixture_p1_b1[off],
                    f"Calibration mismatch at offset {off} in p1_b1",
                )
            self.assertEqual(blocks["p1_b1"][130], fixture_p1_b1[130])
            self.assertEqual(blocks["p1_b1"][131], fixture_p1_b1[131])

    def test_get_factory_blocks_embedded_fallback(self) -> None:
        """Verify fallback to _EMBEDDED_FACTORY_B85 when candidate files are not found."""
        with patch("pathlib.Path.is_file", return_value=False):
            blocks = get_factory_blocks()
            self.assertEqual(len(blocks), 4)
            for k in ("p1_b1", "p1_b2", "p2_b1", "p2_b2"):
                self.assertIn(k, blocks)
                self.assertEqual(len(blocks[k]), 520)
                self.assertEqual(blocks[k][0], 0x04)

    def test_perform_factory_reset_success_sequence(self) -> None:
        mock_dev = MockRecoveryDevice()

        with tempfile.TemporaryDirectory() as tmp_state:
            with patch("icarus.backup.STATE_DIR", Path(tmp_state) / "ctl"), patch(
                "icarus.backup.ALT_STATE_DIR", Path(tmp_state) / "alt"
            ), patch("time.sleep"):  # Speed up tests
                ok, msg = perform_factory_reset(mock_dev)

                self.assertTrue(ok)
                self.assertIn("Factory reset successfully flashed", msg)

                # Exactly 4 blocks written: P2 config, P2 buttons, P1 config, P1 buttons
                self.assertEqual(len(mock_dev.written_blocks), 4)

                # Block 0: Profile 2 config (command 0x21, write magic 0x7B)
                self.assertEqual(mock_dev.written_blocks[0][0], 0x04)
                self.assertEqual(mock_dev.written_blocks[0][1], 0x21)
                self.assertEqual(mock_dev.written_blocks[0][3], 0x7B)

                # Block 1: Profile 2 buttons (command 0x22, write magic 0x50)
                self.assertEqual(mock_dev.written_blocks[1][0], 0x04)
                self.assertEqual(mock_dev.written_blocks[1][1], 0x22)
                self.assertEqual(mock_dev.written_blocks[1][3], 0x50)

                # Block 2: Profile 1 config (command 0x11, write magic 0x7B)
                self.assertEqual(mock_dev.written_blocks[2][0], 0x04)
                self.assertEqual(mock_dev.written_blocks[2][1], 0x11)
                self.assertEqual(mock_dev.written_blocks[2][3], 0x7B)

                # Block 3: Profile 1 buttons (command 0x12, write magic 0x50)
                self.assertEqual(mock_dev.written_blocks[3][0], 0x04)
                self.assertEqual(mock_dev.written_blocks[3][1], 0x12)
                self.assertEqual(mock_dev.written_blocks[3][3], 0x50)

                # Profile toggle: P2 then P1
                self.assertEqual(mock_dev.profile_switches, [2, 1])

    def test_perform_factory_reset_aborts_if_backup_fails(self) -> None:
        mock_dev = MockRecoveryDevice()

        with patch("icarus.recovery.ensure_backup", side_effect=OSError("Disk full")):
            ok, msg = perform_factory_reset(mock_dev)

            self.assertFalse(ok)
            self.assertIn("Pre-reset state backup failed", msg)
            self.assertEqual(len(mock_dev.written_blocks), 0)
            self.assertEqual(len(mock_dev.profile_switches), 0)

    def test_find_motion_node_sysfs_probing(self) -> None:
        """Test sysfs probing finds node matching 258A:0027 and 71-byte descriptor."""
        with tempfile.TemporaryDirectory() as tmp_sysfs:
            sysfs_path = Path(tmp_sysfs)
            dev_entry = sysfs_path / "hidraw0"
            dev_dir = dev_entry / "device"
            dev_dir.mkdir(parents=True)

            (dev_dir / "uevent").write_text("HID_ID=0003:0000258A:00000027.0001\n")
            (dev_dir / "report_descriptor").write_bytes(bytes(71))

            with patch("pathlib.Path.is_dir", return_value=True), patch(
                "icarus.recovery.Path",
                side_effect=lambda p: sysfs_path if p == "/sys/class/hidraw" else Path(p),
            ):
                # When /dev/hidraw0 exists, find_motion_node finds it
                node = find_motion_node()
                self.assertIsInstance(node, Path)

    def test_verify_sensor_motion_missing_node_returns_false(self) -> None:
        with patch("icarus.recovery.find_motion_node", return_value=Path("/dev/nonexistent_hidraw_999")):
            self.assertFalse(verify_sensor_motion(timeout_ms=10))

    def test_verify_sensor_motion_open_error_returns_false(self) -> None:
        with patch("icarus.recovery.find_motion_node", return_value=Path("/dev/null")), patch(
            "os.open", side_effect=PermissionError("Permission denied")
        ):
            self.assertFalse(verify_sensor_motion(timeout_ms=10))

    def test_verify_sensor_motion_receives_motion_packet(self) -> None:
        # Pack standard boot mouse packet: [report_id, dx, dy, wheel, hwheel] (<Bhhbb)
        packet = struct.pack("<Bhhbb", 0x01, 15, -8, 0, 0)

        with patch("icarus.recovery.find_motion_node", return_value=Path("/dev/null")), patch(
            "os.open", return_value=123
        ), patch("os.close"), patch("select.select", return_value=([123], [], [])), patch(
            "os.read", return_value=packet
        ):
            self.assertTrue(verify_sensor_motion(timeout_ms=50))

    def test_verify_sensor_motion_zero_motion_packet_returns_true(self) -> None:
        # Packet received even if dx=0, dy=0 means device interface is active and streaming
        packet = struct.pack("<Bhhbb", 0x01, 0, 0, 0, 0)

        with patch("icarus.recovery.find_motion_node", return_value=Path("/dev/null")), patch(
            "os.open", return_value=123
        ), patch("os.close"), patch("select.select", return_value=([123], [], [])), patch(
            "os.read", return_value=packet
        ):
            self.assertTrue(verify_sensor_motion(timeout_ms=50))

    def test_verify_sensor_motion_timeout_returns_false(self) -> None:
        with patch("icarus.recovery.find_motion_node", return_value=Path("/dev/null")), patch(
            "os.open", return_value=123
        ), patch("os.close"), patch("select.select", return_value=([], [], [])):
            self.assertFalse(verify_sensor_motion(timeout_ms=5))


if __name__ == "__main__":
    unittest.main()
