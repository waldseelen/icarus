"""Unit tests for macro serialization and parsing."""

import unittest

from icarus.macros import (
    MacroCmd,
    MacroEvent,
    OnboardMacro,
    parse_macro,
    serialize_macro,
)


class TestMacros(unittest.TestCase):
    def test_macro_serialization_roundtrip(self) -> None:
        m = OnboardMacro(index=2)
        m.add_key_tap("a", delay_ms=25)
        m.add_btn_click(1, delay_ms=10)

        self.assertEqual(len(m.events), 4)

        buf = serialize_macro(m)
        self.assertEqual(len(buf), 520)
        self.assertEqual(buf[0], 0x04)
        self.assertEqual(buf[1], 0x30)  # CMD_MACRO
        self.assertEqual(buf[2], 0x02)  # WRITE flag
        self.assertEqual(buf[8], 2)  # Macro index
        self.assertEqual(buf[10], 4)  # 4 events

        # Event 0: KeyDown 'a' (0x04)
        self.assertEqual(buf[11], MacroCmd.KEY_PRESS)
        self.assertEqual(buf[12], 25)
        self.assertEqual(buf[13], 0x04)

        # Event 1: KeyUp 'a'
        self.assertEqual(buf[14], MacroCmd.KEY_RELEASE)
        self.assertEqual(buf[15], 25)
        self.assertEqual(buf[16], 0x04)

        # Event 2: BtnDown Left (0x01)
        self.assertEqual(buf[17], MacroCmd.BTN_PRESS)
        self.assertEqual(buf[18], 10)
        self.assertEqual(buf[19], 0x01)

        # Parse back
        m2 = parse_macro(buf)
        self.assertEqual(m2.index, 2)
        self.assertEqual(len(m2.events), 4)
        self.assertEqual(m2.events[0].cmd, MacroCmd.KEY_PRESS)
        self.assertEqual(m2.events[0].code, 0x04)


if __name__ == "__main__":
    unittest.main()
