"""Unit tests for scroll factor management and touchpad isolation."""

import tempfile
import unittest
from pathlib import Path

from icarus.scroll import get_scroll_factor, set_scroll_factor


SAMPLE_INPUT_LUA = """-- Omarchy Hyprland config
hl.config({
  input = {
    sensitivity = 0.25,
    touchpad = {
      natural_scroll = true,
      scroll_factor = 0.6,
      tap_and_drag = true,
    },
  },
})

hl.device({
  name = "sinowealth-wired-gaming-mouse",
  sensitivity = 0.0,
  accel_profile = "flat",
  scroll_factor = 1.6,
})
"""


class TestScroll(unittest.TestCase):
    def test_scroll_factor_bounds(self) -> None:
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".lua") as f:
            f.write(SAMPLE_INPUT_LUA)
            tmp_path = Path(f.name)

        try:
            # Set to 15.0x
            self.assertTrue(set_scroll_factor(15.0, config_path=tmp_path))
            content = tmp_path.read_text(encoding="utf-8")
            self.assertIn("scroll_factor = 15.0,", content)

            # CRITICAL INVARIANT: Touchpad scroll factor must remain 0.6 exactly
            self.assertIn("scroll_factor = 0.6,", content)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_scroll_factor_append_when_missing(self) -> None:
        without_mouse = """hl.config({
  input = {
    touchpad = {
      scroll_factor = 0.6,
    },
  },
})
"""
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".lua") as f:
            f.write(without_mouse)
            tmp_path = Path(f.name)

        try:
            self.assertTrue(set_scroll_factor(8.0, config_path=tmp_path))
            content = tmp_path.read_text(encoding="utf-8")
            self.assertIn('name = "sinowealth-wired-gaming-mouse"', content)
            self.assertIn("scroll_factor = 8.0,", content)
            # Touchpad still untouched
            self.assertIn("scroll_factor = 0.6,", content)
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
