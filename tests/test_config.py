"""Unit tests for config parser and serializer."""

import unittest
from pathlib import Path

from icarus.config import (
    RgbEffect,
    dpi_to_raw,
    parse_config,
    permute_color_from_hw,
    permute_color_to_hw,
    raw_to_dpi,
    serialize_config,
)

DATA_DIR = Path(__file__).resolve().parent / "data"


class TestConfig(unittest.TestCase):
    def test_dpi_conversion_roundtrip(self) -> None:
        cases = [
            (400, 3),
            (500, 4),
            (800, 7),
            (1000, 9),
            (1500, 14),
            (2000, 19),
            (3000, 29),
            (4000, 39),
            (5000, 49),
            (6000, 51),
            (8000, 55),
            (10000, 59),
        ]
        for dpi, raw in cases:
            self.assertEqual(dpi_to_raw(dpi), raw, f"dpi_to_raw({dpi}) != {raw}")
            self.assertEqual(raw_to_dpi(raw), dpi, f"raw_to_dpi({raw}) != {dpi}")

    def test_parse_p1_b1(self) -> None:
        data = (DATA_DIR / "p1_b1.bin").read_bytes()
        cfg = parse_config(data)
        self.assertEqual(cfg.profile, 1)
        self.assertEqual(cfg.polling_rate, 1000)
        self.assertEqual(cfg.active_dpi_stage, 4)
        self.assertEqual(len(cfg.dpi_stages), 8)
        self.assertEqual(cfg.dpi_stages[0].dpi, 500)
        self.assertEqual(cfg.dpi_stages[1].dpi, 800)
        self.assertEqual(cfg.dpi_stages[2].dpi, 1000)
        self.assertEqual(cfg.dpi_stages[3].dpi, 1100)
        self.assertEqual(cfg.dpi_stages[4].dpi, 1200)
        self.assertEqual(cfg.dpi_stages[5].dpi, 1500)
        self.assertEqual(cfg.dpi_stages[6].dpi, 4000)
        self.assertEqual(cfg.dpi_stages[7].dpi, 5000)
        self.assertEqual(cfg.rgb_effect, RgbEffect.BREATHING)
        self.assertEqual(cfg.lod, 1)

        # Roundtrip serialization
        ser = serialize_config(cfg)
        self.assertEqual(len(ser), 520)
        self.assertEqual(ser[0], 0x04)
        self.assertEqual(ser[1], 0x11)
        self.assertEqual(ser[3], 0x7B)  # write magic
        # Verify values survived
        cfg2 = parse_config(ser)
        self.assertEqual(cfg2.profile, 1)
        self.assertEqual(cfg2.polling_rate, 1000)
        self.assertEqual(cfg2.active_dpi_stage, 4)
        self.assertEqual(cfg2.dpi_stages[0].dpi, 500)
        self.assertEqual(cfg2.lod, 1)

    def test_parse_p2_b1(self) -> None:
        data = (DATA_DIR / "p2_b1.bin").read_bytes()
        cfg = parse_config(data)
        self.assertEqual(cfg.profile, 2)
        self.assertEqual(cfg.polling_rate, 250)
        self.assertEqual(cfg.active_dpi_stage, 3)
        self.assertEqual(len(cfg.dpi_stages), 8)
        self.assertEqual(cfg.dpi_stages[0].dpi, 500)
        self.assertEqual(cfg.dpi_stages[1].dpi, 800)
        self.assertEqual(cfg.dpi_stages[2].dpi, 1000)
        self.assertEqual(cfg.dpi_stages[3].dpi, 1500)
        self.assertEqual(cfg.dpi_stages[4].dpi, 2000)
        self.assertEqual(cfg.dpi_stages[5].dpi, 3000)
        self.assertEqual(cfg.dpi_stages[6].dpi, 4000)
        self.assertEqual(cfg.dpi_stages[7].dpi, 5000)
        self.assertEqual(cfg.rgb_effect, RgbEffect.STEADY)
        self.assertEqual(cfg.lod, 0)

    def test_channel_order_permutation(self) -> None:
        rgb = (255, 128, 64)
        # Standard RGB
        self.assertEqual(permute_color_to_hw(rgb, "RGB"), (255, 128, 64))
        self.assertEqual(permute_color_from_hw((255, 128, 64), "RGB"), rgb)

        # GRB (Green-Red-Blue)
        grb_hw = permute_color_to_hw(rgb, "GRB")
        self.assertEqual(grb_hw, (128, 255, 64))
        self.assertEqual(permute_color_from_hw(grb_hw, "GRB"), rgb)

        # BGR (Blue-Green-Red)
        bgr_hw = permute_color_to_hw(rgb, "BGR")
        self.assertEqual(bgr_hw, (64, 128, 255))
        self.assertEqual(permute_color_from_hw(bgr_hw, "BGR"), rgb)

    def test_breathing_color_sync(self) -> None:
        data = (DATA_DIR / "p1_b1.bin").read_bytes()
        cfg = parse_config(data)
        cfg.rgb_effect = RgbEffect.BREATHING
        cfg.single_color = (0, 255, 128)
        cfg.breathing_colors = []  # Empty palette, must auto-sync single_color
        ser = serialize_config(cfg)
        self.assertEqual(ser[53], int(RgbEffect.BREATHING))
        self.assertEqual(ser[61], 1)  # b_count = 1
        self.assertEqual((ser[62], ser[63], ser[64]), (0, 255, 128))

    def test_sensor_calibration_bytes_preserved(self) -> None:
        """Ensure serialize_config strictly preserves sensor calibration bytes (104..128, 130..131)."""
        for fixture_name in ("p1_b1.bin", "p2_b1.bin"):
            data = (DATA_DIR / fixture_name).read_bytes()
            cfg = parse_config(data)
            # Change arbitrary user settings (rate, dpi, led)
            cfg.polling_rate = 500
            cfg.rgb_effect = RgbEffect.STEADY
            cfg.single_color = (12, 34, 56)
            ser = serialize_config(cfg)
            # Assert calibration bytes 104..128 (excluding lod at 129) and 130..131 match original byte-exact
            for i in range(104, 129):
                self.assertEqual(ser[i], data[i], f"Mismatch at offset {i} for {fixture_name}")
            self.assertEqual(ser[130], data[130], f"Mismatch at offset 130 for {fixture_name}")
            self.assertEqual(ser[131], data[131], f"Mismatch at offset 131 for {fixture_name}")


if __name__ == "__main__":
    unittest.main()
