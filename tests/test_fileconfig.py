"""Unit tests for declarative JSON configuration."""

import json
import tempfile
import unittest
from pathlib import Path

from icarus.fileconfig import hex_to_color, color_to_hex, load_config_file, save_config_file


class TestFileConfig(unittest.TestCase):
    def test_color_hex_conversions(self) -> None:
        self.assertEqual(color_to_hex((255, 0, 128)), "#ff0080")
        self.assertEqual(hex_to_color("#ff0080"), (255, 0, 128))

    def test_save_and_load_config(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            p = Path(f.name)
            data = {
                "active_profile": 1,
                "profiles": {
                    "1": {
                        "name": "Default",
                        "polling_rate_hz": 1000,
                        "lod": "3mm",
                    }
                },
            }
            save_config_file(data, p)
            loaded = load_config_file(p)
            self.assertEqual(loaded["active_profile"], 1)
            self.assertEqual(loaded["profiles"]["1"]["polling_rate_hz"], 1000)


if __name__ == "__main__":
    unittest.main()
