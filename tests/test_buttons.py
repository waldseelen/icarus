"""Unit tests for button map parser and serializer."""

import unittest
from pathlib import Path

from icarus.buttons import (
    ButtonBinding,
    ButtonType,
    ClickCode,
    DpiSwitchCode,
    MultiClickCode,
    make_multiclick_binding,
    make_multimedia_binding,
    make_special_binding,
    parse_buttons,
    serialize_buttons,
)

DATA_DIR = Path(__file__).resolve().parent / "data"


class TestButtons(unittest.TestCase):
    def test_parse_p1_b2(self) -> None:
        data = (DATA_DIR / "p1_b2.bin").read_bytes()
        tbl = parse_buttons(data)
        self.assertEqual(tbl.profile, 1)
        self.assertEqual(len(tbl.buttons), 20)

        # K1 = Left Click
        self.assertEqual(tbl.buttons[0].btype, ButtonType.MOUSE_CLICK)
        self.assertEqual(tbl.buttons[0].data0, ClickCode.LEFT)

        # K2 = Right Click
        self.assertEqual(tbl.buttons[1].btype, ButtonType.MOUSE_CLICK)
        self.assertEqual(tbl.buttons[1].data0, ClickCode.RIGHT)

        # K3 = Middle Click
        self.assertEqual(tbl.buttons[2].btype, ButtonType.MOUSE_CLICK)
        self.assertEqual(tbl.buttons[2].data0, ClickCode.MIDDLE)

        # K5 = Back
        self.assertEqual(tbl.buttons[4].btype, ButtonType.MOUSE_CLICK)
        self.assertEqual(tbl.buttons[4].data0, ClickCode.BACK)

        # Roundtrip
        ser = serialize_buttons(tbl)
        self.assertEqual(len(ser), 520)
        self.assertEqual(ser[0], 0x04)
        self.assertEqual(ser[1], 0x12)
        self.assertEqual(ser[3], 0x50)  # button write magic

        tbl2 = parse_buttons(ser)
        self.assertEqual(tbl2.profile, 1)
        self.assertEqual(tbl2.buttons[0].data0, ClickCode.LEFT)

    def test_parse_p2_b2(self) -> None:
        data = (DATA_DIR / "p2_b2.bin").read_bytes()
        tbl = parse_buttons(data)
        self.assertEqual(tbl.profile, 2)

        # K6 = DPI Up (0x41, 0x01)
        self.assertEqual(tbl.buttons[5].btype, ButtonType.DPI_SWITCH)
        self.assertEqual(tbl.buttons[5].data0, DpiSwitchCode.UP)

        # K7 = DPI Down (0x41, 0x02)
        self.assertEqual(tbl.buttons[6].btype, ButtonType.DPI_SWITCH)
        self.assertEqual(tbl.buttons[6].data0, DpiSwitchCode.DOWN)

    def test_multimedia_presets(self) -> None:
        b_play = make_multimedia_binding(1, "play_pause")
        self.assertEqual(b_play.btype, ButtonType.MULTIMEDIA)
        self.assertEqual(b_play.data0, 0x08)
        self.assertEqual(b_play.summary(), "Play / Pause")

        b_next = make_multimedia_binding(2, "next_track")
        self.assertEqual(b_next.data0, 0x01)
        self.assertEqual(b_next.summary(), "Next Track")

        b_volup = make_multimedia_binding(3, "volume_up")
        self.assertEqual(b_volup.data0, 0x40)
        self.assertEqual(b_volup.summary(), "Volume Up")

        b_calc = make_multimedia_binding(4, "calculator")
        self.assertEqual(b_calc.data1, 0x20)
        self.assertEqual(b_calc.summary(), "Calculator")

    def test_special_hardware_toggles(self) -> None:
        b_prof = make_special_binding(1, "profile_switch")
        self.assertEqual(b_prof.btype, ButtonType.SPECIAL)
        self.assertEqual(b_prof.data0, 0x01)
        self.assertEqual(b_prof.summary(), "Switch Profile (Mode)")

        b_poll = make_special_binding(2, "polling_rate_switch")
        self.assertEqual(b_poll.data0, 0x02)
        self.assertEqual(b_poll.summary(), "Switch Polling Rate")

        b_light = make_special_binding(3, "lighting_toggle")
        self.assertEqual(b_light.data0, 0x04)
        self.assertEqual(b_light.summary(), "Lighting ON / OFF")

    def test_multiclick_presets(self) -> None:
        b_double = make_multiclick_binding(1, 2)
        self.assertEqual(b_double.btype, ButtonType.MULTI_CLICK)
        self.assertEqual(b_double.data0, 0x01)
        self.assertEqual(b_double.summary(), "Double Click")

        b_triple = make_multiclick_binding(2, 3)
        self.assertEqual(b_triple.btype, ButtonType.MULTI_CLICK)
        self.assertEqual(b_triple.data0, 0x02)
        self.assertEqual(b_triple.summary(), "Triple Click")


if __name__ == "__main__":
    unittest.main()
