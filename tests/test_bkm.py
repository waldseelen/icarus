"""Unit tests for .BKM parsing and TEA decryption."""

import unittest
from pathlib import Path

from icarus.bkm import parse_bkm

BKM_DIR = Path("/run/media/hp/SSS/WIN/App_Configs")


class TestBkm(unittest.TestCase):
    def test_parse_lol_bkm(self) -> None:
        p = BKM_DIR / "LOL.bkm"
        if not p.is_file():
            self.skipTest(f"{p} not found")

        bkm = parse_bkm(p)
        self.assertEqual(bkm.title, "LOL")
        self.assertGreaterEqual(len(bkm.macros), 1)

        # Verify that macro 2 has name 'seskonusma'
        macro_names = [m.name for m in bkm.macros]
        self.assertIn("seskonusma", macro_names)

    def test_parse_obsidian_bkm(self) -> None:
        p = BKM_DIR / "OBSIDIAN.bkm"
        if not p.is_file():
            self.skipTest(f"{p} not found")

        bkm = parse_bkm(p)
        self.assertEqual(bkm.title, "BEST")
        self.assertGreaterEqual(len(bkm.macros), 1)

    def test_parse_general_bkm(self) -> None:
        p = BKM_DIR / "GENERAL.bkm"
        if not p.is_file():
            self.skipTest(f"{p} not found")

        bkm = parse_bkm(p)
        self.assertEqual(bkm.title, "LOL")


if __name__ == "__main__":
    unittest.main()
