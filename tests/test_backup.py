"""Unit tests for backup management and pre-write state dumping."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icarus.backup import ensure_backup, restore_backup, verify_backup
from icarus.protocol import BLOCK_BUTTONS, BLOCK_CONFIG, Device


class MockTransport:
    """Mock Hidraw transport for testing Device interactions."""

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


class MockDevice(Device):
    """Mock Device that records reads and writes without touching hardware."""

    def __init__(self) -> None:
        super().__init__(MockTransport())  # type: ignore[arg-type]
        self.blocks: dict[tuple[int, int], bytes] = {
            (1, BLOCK_CONFIG): bytes([0x04, 0x11, 0x00, 0x00] + [0xAA] * 516),
            (1, BLOCK_BUTTONS): bytes([0x04, 0x12, 0x00, 0x00] + [0xBB] * 516),
            (2, BLOCK_CONFIG): bytes([0x04, 0x21, 0x00, 0x00] + [0xCC] * 516),
            (2, BLOCK_BUTTONS): bytes([0x04, 0x22, 0x00, 0x00] + [0xDD] * 516),
        }
        self.read_calls: list[tuple[int, int]] = []
        self.written_blocks: list[bytes] = []
        self.active_prof: int = 1

    def read_block(self, profile: int, block_type: int) -> bytes:
        self.read_calls.append((profile, block_type))
        return self.blocks[(profile, block_type)]

    def write_block(self, data: bytes) -> None:
        self.written_blocks.append(data)

    def active_profile(self) -> int:
        return self.active_prof

    def set_active_profile(self, profile: int) -> None:
        self.active_prof = profile


class TestBackup(unittest.TestCase):
    """Test suite for icarus.backup module."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp_dir.name) / "icarusctl"
        self.alt_state_dir = Path(self.temp_dir.name) / "icarus"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.alt_state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ensure_backup_creates_all_four_blocks(self) -> None:
        mock_dev = MockDevice()

        with patch("icarus.backup.STATE_DIR", self.state_dir), patch(
            "icarus.backup.ALT_STATE_DIR", self.alt_state_dir
        ):
            backup_path = ensure_backup(mock_dev)

            self.assertTrue(backup_path.is_dir())
            self.assertTrue(str(backup_path).startswith(str(self.state_dir)))

            # Verify all 4 blocks read from device
            expected_reads = [
                (1, BLOCK_CONFIG),
                (1, BLOCK_BUTTONS),
                (2, BLOCK_CONFIG),
                (2, BLOCK_BUTTONS),
            ]
            self.assertEqual(mock_dev.read_calls, expected_reads)

            # Verify files in primary backup path
            for p in (1, 2):
                b1_file = backup_path / f"p{p}_b1.bin"
                b2_file = backup_path / f"p{p}_b2.bin"
                self.assertTrue(b1_file.is_file())
                self.assertTrue(b2_file.is_file())
                self.assertEqual(b1_file.stat().st_size, 520)
                self.assertEqual(b2_file.stat().st_size, 520)
                self.assertEqual(b1_file.read_bytes(), mock_dev.blocks[(p, BLOCK_CONFIG)])
                self.assertEqual(b2_file.read_bytes(), mock_dev.blocks[(p, BLOCK_BUTTONS)])

            # Verify files in alternate backup path
            alt_backup_path = self.alt_state_dir / backup_path.name
            self.assertTrue(alt_backup_path.is_dir())
            for p in (1, 2):
                self.assertEqual(
                    (alt_backup_path / f"p{p}_b1.bin").read_bytes(),
                    mock_dev.blocks[(p, BLOCK_CONFIG)],
                )
                self.assertEqual(
                    (alt_backup_path / f"p{p}_b2.bin").read_bytes(),
                    mock_dev.blocks[(p, BLOCK_BUTTONS)],
                )

    def test_verify_backup_valid_directory(self) -> None:
        backup_dir = self.state_dir / "valid_backup"
        backup_dir.mkdir(parents=True)
        for p in (1, 2):
            (backup_dir / f"p{p}_b1.bin").write_bytes(bytes(520))
            (backup_dir / f"p{p}_b2.bin").write_bytes(bytes(520))

        self.assertTrue(verify_backup(backup_dir))

    def test_verify_backup_missing_file_rejected(self) -> None:
        backup_dir = self.state_dir / "incomplete_backup"
        backup_dir.mkdir(parents=True)
        (backup_dir / "p1_b1.bin").write_bytes(bytes(520))
        (backup_dir / "p1_b2.bin").write_bytes(bytes(520))
        (backup_dir / "p2_b1.bin").write_bytes(bytes(520))
        # Missing p2_b2.bin
        self.assertFalse(verify_backup(backup_dir))

    def test_verify_backup_incorrect_file_size_rejected(self) -> None:
        backup_dir = self.state_dir / "bad_size_backup"
        backup_dir.mkdir(parents=True)
        (backup_dir / "p1_b1.bin").write_bytes(bytes(520))
        (backup_dir / "p1_b2.bin").write_bytes(bytes(519))  # 1 byte short
        (backup_dir / "p2_b1.bin").write_bytes(bytes(520))
        (backup_dir / "p2_b2.bin").write_bytes(bytes(520))
        self.assertFalse(verify_backup(backup_dir))

        # Test oversize
        (backup_dir / "p1_b2.bin").write_bytes(bytes(521))
        self.assertFalse(verify_backup(backup_dir))

    def test_verify_backup_nonexistent_and_file_paths(self) -> None:
        non_existent = self.state_dir / "does_not_exist"
        self.assertFalse(verify_backup(non_existent))

        dummy_file = self.state_dir / "not_a_dir.bin"
        dummy_file.write_bytes(bytes(520))
        self.assertFalse(verify_backup(dummy_file))

    def test_restore_backup_success(self) -> None:
        mock_dev = MockDevice()
        backup_dir = self.state_dir / "restore_test"
        backup_dir.mkdir(parents=True)

        p1_b1_data = bytes([0x04, 0x11, 0x00, 0x00] + [0x11] * 516)
        p1_b2_data = bytes([0x04, 0x12, 0x00, 0x00] + [0x22] * 516)
        p2_b1_data = bytes([0x04, 0x21, 0x00, 0x00] + [0x33] * 516)
        p2_b2_data = bytes([0x04, 0x22, 0x00, 0x00] + [0x44] * 516)

        (backup_dir / "p1_b1.bin").write_bytes(p1_b1_data)
        (backup_dir / "p1_b2.bin").write_bytes(p1_b2_data)
        (backup_dir / "p2_b1.bin").write_bytes(p2_b1_data)
        (backup_dir / "p2_b2.bin").write_bytes(p2_b2_data)

        success = restore_backup(mock_dev, backup_dir)
        self.assertTrue(success)

        # 4 blocks written: p1_b1, p1_b2, p2_b1, p2_b2
        self.assertEqual(len(mock_dev.written_blocks), 4)

        # Check write magics applied to byte index 3
        # Config blocks must have write magic 0x7B
        self.assertEqual(mock_dev.written_blocks[0][3], 0x7B)
        self.assertEqual(mock_dev.written_blocks[2][3], 0x7B)
        # Button blocks must have write magic 0x50
        self.assertEqual(mock_dev.written_blocks[1][3], 0x50)
        self.assertEqual(mock_dev.written_blocks[3][3], 0x50)

        # Lengths must all be 520 bytes
        for b in mock_dev.written_blocks:
            self.assertEqual(len(b), 520)

        # Check payload preservation
        self.assertEqual(mock_dev.written_blocks[0][4:], p1_b1_data[4:])
        self.assertEqual(mock_dev.written_blocks[1][4:], p1_b2_data[4:])
        self.assertEqual(mock_dev.written_blocks[2][4:], p2_b1_data[4:])
        self.assertEqual(mock_dev.written_blocks[3][4:], p2_b2_data[4:])

    def test_restore_backup_aborts_on_invalid_backup(self) -> None:
        mock_dev = MockDevice()
        bad_dir = self.state_dir / "bad_dir"
        bad_dir.mkdir(parents=True)
        (bad_dir / "p1_b1.bin").write_bytes(bytes(100))  # Invalid size

        success = restore_backup(mock_dev, bad_dir)
        self.assertFalse(success)
        self.assertEqual(len(mock_dev.written_blocks), 0)


if __name__ == "__main__":
    unittest.main()
