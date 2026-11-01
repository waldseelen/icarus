"""Unit tests for LED modes, LED_MASK enforcement, and safe RGB effect handling."""

from __future__ import annotations

import argparse
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from icarus.commands import cmd_led
from icarus.config import (
    LED_MASK,
    SUPPORTED_LED_MODES,
    SUPPORTED_RGB_EFFECTS,
    MouseConfig,
    RgbEffect,
    is_led_mode_supported,
    parse_config,
    serialize_config,
)

DATA_DIR = Path(__file__).resolve().parent / "data"


class TestLedModes(unittest.TestCase):
    """Test suite covering LED_MASK, supported modes, rejection of unsafe modes, and serialization."""

    def test_led_mask_constant_and_bit_properties(self) -> None:
        """Verify LED_MASK equals 0x1E8 and corresponds to masked unsafe modes."""
        self.assertEqual(LED_MASK, 0x1E8, "LED_MASK must equal 0x1E8 (488)")

        # Verify bits set in LED_MASK:
        # 0x1E8 = 0b111101000 -> bits 3, 5, 6, 7, 8
        masked_bits = [bit for bit in range(10) if (LED_MASK & (1 << bit))]
        self.assertEqual(masked_bits, [3, 5, 6, 7, 8])

        # Verify unmasked bits in range 0..9:
        unmasked_bits = [bit for bit in range(10) if not (LED_MASK & (1 << bit))]
        self.assertEqual(unmasked_bits, [0, 1, 2, 4, 9])

    def test_supported_led_modes_mapping(self) -> None:
        """Verify SUPPORTED_LED_MODES dictionary maps exact IDs to expected names."""
        expected = {
            0: "streaming",
            1: "steady",
            2: "breathing",
            4: "neon",
            9: "off",
        }
        self.assertEqual(SUPPORTED_LED_MODES, expected)

        # Verify SUPPORTED_RGB_EFFECTS tuple contains the corresponding enum values
        expected_effects = (
            RgbEffect.STREAMING,
            RgbEffect.STEADY,
            RgbEffect.BREATHING,
            RgbEffect.NEON,
            RgbEffect.OFF,
        )
        self.assertEqual(SUPPORTED_RGB_EFFECTS, expected_effects)

    def test_is_led_mode_supported_accepts_valid_modes(self) -> None:
        """Verify is_led_mode_supported returns True for modes 0, 1, 2, 4, 9 and enums."""
        valid_int_modes = [0, 1, 2, 4, 9]
        for m in valid_int_modes:
            self.assertTrue(is_led_mode_supported(m), f"Mode {m} should be supported")

        valid_enum_modes = [
            RgbEffect.STREAMING,
            RgbEffect.STEADY,
            RgbEffect.BREATHING,
            RgbEffect.NEON,
            RgbEffect.OFF,
        ]
        for eff in valid_enum_modes:
            self.assertTrue(is_led_mode_supported(eff), f"Effect {eff} should be supported")

    def test_is_led_mode_supported_rejects_unsafe_modes(self) -> None:
        """Verify is_led_mode_supported returns False for masked modes (3, 5, 6, 7, 8)."""
        unsafe_modes = [
            (3, RgbEffect.COLORFUL_TAIL),
            (5, RgbEffect.COLORFUL_STEADY),
            (6, RgbEffect.FLICKER),
            (7, RgbEffect.STARS_TWINKLE),
            (8, RgbEffect.WAVE),
        ]
        for mode_id, enum_val in unsafe_modes:
            self.assertFalse(
                is_led_mode_supported(mode_id),
                f"Mode {mode_id} is in LED_MASK and must be rejected to protect PMW3325 registers",
            )
            self.assertFalse(
                is_led_mode_supported(enum_val),
                f"Enum {enum_val.name} must be rejected",
            )

    def test_is_led_mode_supported_rejects_out_of_range(self) -> None:
        """Verify is_led_mode_supported rejects negative and >9 integers."""
        for bad_val in (-1, -10, 10, 11, 255):
            self.assertFalse(is_led_mode_supported(bad_val))

    def test_config_serialization_for_all_supported_modes(self) -> None:
        """Verify serializing config with all supported modes preserves calibration bytes."""
        fixture_data = (DATA_DIR / "p1_b1.bin").read_bytes()

        for eff in SUPPORTED_RGB_EFFECTS:
            cfg = parse_config(fixture_data)
            cfg.rgb_effect = eff
            cfg.rgb_brightness = 3
            cfg.rgb_speed = 2
            cfg.rgb_direction = 0

            ser = serialize_config(cfg)
            self.assertEqual(len(ser), 520)
            self.assertEqual(ser[0], 0x04)
            self.assertEqual(ser[1], 0x11)
            self.assertEqual(ser[3], 0x7B)  # write magic
            self.assertEqual(ser[53], int(eff), f"Byte 53 should contain mode {eff.value}")

            # Verify PMW3325 calibration offsets 104..128 and 130..131 match fixture exactly
            for off in range(104, 129):
                self.assertEqual(
                    ser[off],
                    fixture_data[off],
                    f"Calibration corrupted at offset {off} for effect {eff.name}",
                )
            self.assertEqual(ser[130], fixture_data[130])
            self.assertEqual(ser[131], fixture_data[131])

    def test_cmd_led_list_flag(self) -> None:
        """Verify cmd_led --list outputs supported effects and returns 0."""
        args = argparse.Namespace(list=True)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            ret = cmd_led(args)
            self.assertEqual(ret, 0)

        out = buf.getvalue()
        self.assertIn("Supported LED effects", out)
        for name in SUPPORTED_LED_MODES.values():
            self.assertIn(name, out)

    def test_cmd_led_rejects_unsupported_effect_name(self) -> None:
        """Verify cmd_led rejects unsupported or masked effect names."""
        # Mock _update_config so we can test the callback behavior
        with patch("icarus.commands._update_config") as mock_update:
            args = argparse.Namespace(
                list=False,
                effect="circulation",  # Unsafe masked mode 3
                brightness=None,
                speed=None,
                direction=None,
                color=None,
                breathing_colors=None,
            )
            cmd_led(args)

            # Inspect the closure passed to _update_config
            self.assertTrue(mock_update.called)
            apply_fn = mock_update.call_args[0][0]

            dummy_cfg = MouseConfig(profile=1, polling_rate=1000, active_dpi_stage=1)
            err_buf = io.StringIO()
            with patch("sys.stderr", err_buf):
                res = apply_fn(dummy_cfg, 1)
                self.assertEqual(res, "")
                self.assertIn("Unsupported effect: circulation", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
