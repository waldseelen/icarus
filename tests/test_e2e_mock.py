"""Comprehensive automated unit tests with mock packets for icarusctl.

Covers:
- Report 0x04 generation for all 11 RGB modes & register slice preservation
- All 57 PixArt PMW3325 discrete DPI steps and boundary conditions
- Button calibration (K4/K5 pin swap, K8 Fire, K9 Sniper)
- Macro serialization (12-bit delays, all event types, loop modes, slot limits)
"""

from __future__ import annotations

import unittest

from icarus.buttons import (
    ACTION_FIRE,
    ACTION_SNIPER,
    BUTTON_NAMES,
    PHYSICAL_TO_SLOT,
    SLOT_TO_PHYSICAL,
    ButtonBinding,
    ButtonTable,
    ButtonType,
    ClickCode,
    make_fire_binding,
    make_macro_binding,
    make_sniper_binding,
    parse_buttons,
    serialize_buttons,
)
from icarus.config import (
    RATE_TO_RAW,
    VALID_DPIS,
    DpiStage,
    MouseConfig,
    RgbEffect,
    dpi_to_raw,
    parse_config,
    raw_to_dpi,
    serialize_config,
    snap_dpi,
)
from icarus.macros import (
    MAX_MACRO_EVENTS,
    MacroCmd,
    MacroEvent,
    MacroLoopMode,
    OnboardMacro,
    parse_macro,
    serialize_macro,
)


def _make_base_config() -> MouseConfig:
    """Helper to create standard 8-stage base configuration."""
    stages = [
        DpiStage(500, (255, 0, 0), True),
        DpiStage(800, (0, 0, 255), True),
        DpiStage(1000, (0, 255, 0), True),
        DpiStage(1500, (255, 0, 255), True),
        DpiStage(2000, (255, 128, 0), True),
        DpiStage(3000, (255, 255, 0), True),
        DpiStage(4000, (0, 255, 255), True),
        DpiStage(5000, (255, 255, 255), True),
    ]
    return MouseConfig(
        profile=1,
        polling_rate=1000,
        active_dpi_stage=1,
        dpi_stages=stages,
        raw_buffer=bytearray(520),
    )


class TestRgbModesReportGeneration(unittest.TestCase):
    """Test Report 0x04 wire generation for all 11 RGB modes."""

    def test_all_11_rgb_modes_report_generation(self) -> None:
        cfg = _make_base_config()
        cfg.rgb_brightness = 4
        cfg.rgb_speed = 2

        # Mode 0: Colorful Streaming (B54=bri/spd, B55=dir)
        cfg.rgb_effect = RgbEffect.STREAMING
        cfg.rgb_direction = 1
        buf = serialize_config(cfg)
        self.assertEqual(buf[0], 0x04)
        self.assertEqual(buf[1], 0x11)
        self.assertEqual(buf[3], 0x7B)
        self.assertEqual(buf[53], 0x00)
        self.assertEqual(buf[54], (4 << 4) | 2)
        self.assertEqual(buf[55], 1)

        # Mode 1: Steady (B56=bri, B57..59=RGB)
        cfg.rgb_effect = RgbEffect.STEADY
        cfg.single_color = (255, 128, 64)
        buf = serialize_config(cfg)
        self.assertEqual(buf[53], 0x01)
        self.assertEqual(buf[56] >> 4, 4)
        self.assertEqual((buf[57], buf[58], buf[59]), (255, 128, 64))

        # Mode 2: Breathing (B60=bri/spd, B61=count, B62..82=colors)
        cfg.rgb_effect = RgbEffect.BREATHING
        cfg.breathing_colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        buf = serialize_config(cfg)
        self.assertEqual(buf[53], 0x02)
        self.assertEqual(buf[60], (4 << 4) | 2)
        self.assertEqual(buf[61], 3)
        self.assertEqual(buf[62:65], bytes([255, 0, 0]))
        self.assertEqual(buf[65:68], bytes([0, 255, 0]))
        self.assertEqual(buf[68:71], bytes([0, 0, 255]))

        # Mode 4: Neon (B84=bri/spd)
        cfg.rgb_effect = RgbEffect.NEON
        buf = serialize_config(cfg)
        self.assertEqual(buf[53], 0x04)
        self.assertEqual(buf[84], (4 << 4) | 2)

        # Mode 9: LED OFF (B53=9)
        cfg.rgb_effect = RgbEffect.OFF
        buf = serialize_config(cfg)
        self.assertEqual(buf[53], 0x09)

    def test_dedicated_register_slices_preserved(self) -> None:
        """Switching active mode must not overwrite parameters of other modes."""
        raw = bytearray(520)
        # Seed distinct non-zero sentinel bytes in dedicated slices
        raw[54], raw[55] = 0x31, 0x01  # Streaming (spd=1, bri=3, dir=1)
        raw[56], raw[57:60] = 0x20, b"\x11\x22\x33"  # Steady (bri=2, RGB)
        raw[60], raw[61] = 0x43, 0x02  # Breathing (spd=3, bri=4, count=2)
        raw[62:68] = b"\xAA\xBB\xCC\xDD\xEE\xFF"  # Breathing colors
        raw[83], raw[84], raw[85] = 0x12, 0x34, 0x40  # Tail, Neon, Colorful Steady
        raw[116], raw[117:123] = 0x23, b"\x01\x02\x03\x04\x05\x06"  # Flicker
        raw[123], raw[124], raw[125] = 0x31, 0x32, 0x03  # Stars, Wave, Reaction

        cfg = _make_base_config()
        cfg.raw_buffer = bytearray(raw)

        # Switch to Mode 4 (Neon) with new speed 1, brightness 2
        cfg.rgb_effect = RgbEffect.NEON
        cfg.rgb_speed = 1
        cfg.rgb_brightness = 2
        ser = serialize_config(cfg)

        self.assertEqual(ser[53], 0x04)
        self.assertEqual(ser[84], (2 << 4) | 1)  # Mode 4 updated
        # Slices for all other modes remain intact
        self.assertEqual((ser[54], ser[55]), (0x31, 0x01))
        self.assertEqual(ser[57:60], b"\x11\x22\x33")
        self.assertEqual((ser[60], ser[61]), (0x43, 0x02))
        self.assertEqual(ser[62:68], b"\xAA\xBB\xCC\xDD\xEE\xFF")
        self.assertEqual(ser[83], 0x12)
        self.assertEqual(ser[116], 0x23)
        self.assertEqual(ser[117:123], b"\x01\x02\x03\x04\x05\x06")
        self.assertEqual((ser[123], ser[124], ser[125]), (0x31, 0x32, 0x03))


class TestDpiStepsAndBoundaries(unittest.TestCase):
    """Test all 57 PixArt PMW3325 discrete DPI steps and boundary math."""

    def test_all_57_discrete_dpi_steps(self) -> None:
        self.assertEqual(len(VALID_DPIS), 57)
        for expected_raw_offset, dpi in enumerate(VALID_DPIS):
            expected_raw = 3 + expected_raw_offset
            raw = dpi_to_raw(dpi)
            self.assertEqual(raw, expected_raw, f"dpi_to_raw({dpi}) error")
            back_dpi = raw_to_dpi(raw)
            self.assertEqual(back_dpi, dpi, f"raw_to_dpi({raw}) error")

    def test_optical_vs_interpolated_boundaries(self) -> None:
        # Optical range: 400..5000 (100 CPI step, raw 3..49)
        self.assertEqual(dpi_to_raw(400), 3)
        self.assertEqual(dpi_to_raw(5000), 49)
        self.assertEqual(raw_to_dpi(3), 400)
        self.assertEqual(raw_to_dpi(49), 5000)

        # Interpolated range: 5500..10000 (500 CPI step, raw 50..59)
        self.assertEqual(dpi_to_raw(5500), 50)
        self.assertEqual(dpi_to_raw(10000), 59)
        self.assertEqual(raw_to_dpi(50), 5500)
        self.assertEqual(raw_to_dpi(59), 10000)

        # Snapping and out-of-range bounds
        self.assertEqual(snap_dpi(5200), 5000)
        self.assertEqual(snap_dpi(5300), 5500)
        with self.assertRaises(ValueError):
            dpi_to_raw(350)
        with self.assertRaises(ValueError):
            dpi_to_raw(10500)


class TestButtonMappingAndCalibration(unittest.TestCase):
    """Test physical button calibration and pin routing."""

    def test_button_calibration_and_pin_swap(self) -> None:
        # Physical K4 (Forward) -> Slot 5; Physical K5 (Back) -> Slot 4
        self.assertEqual(PHYSICAL_TO_SLOT[4], 5)
        self.assertEqual(PHYSICAL_TO_SLOT[5], 4)
        self.assertEqual(SLOT_TO_PHYSICAL[5], 4)
        self.assertEqual(SLOT_TO_PHYSICAL[4], 5)

        # Names calibration
        self.assertIn("Forward", BUTTON_NAMES[4])
        self.assertIn("Back", BUTTON_NAMES[5])
        self.assertIn("Fire Key", BUTTON_NAMES[8])
        self.assertIn("Sniper", BUTTON_NAMES[9])

        # Test wire mapping serialization
        tbl = ButtonTable(profile=1)
        tbl.buttons = [
            ButtonBinding(1, ButtonType.MOUSE_CLICK, ClickCode.LEFT),
            ButtonBinding(2, ButtonType.MOUSE_CLICK, ClickCode.RIGHT),
            ButtonBinding(3, ButtonType.MOUSE_CLICK, ClickCode.MIDDLE),
            ButtonBinding(4, ButtonType.MOUSE_CLICK, ClickCode.BACK),
            ButtonBinding(5, ButtonType.MOUSE_CLICK, ClickCode.FORWARD),
        ] + [ButtonBinding(i, ButtonType.DISABLED) for i in range(6, 21)]

        wire = serialize_buttons(tbl)
        self.assertEqual(wire[0], 0x04)
        self.assertEqual(wire[1], 0x12)  # Profile 1 buttons cmd
        self.assertEqual(wire[3], 0x50)  # Buttons write magic

        # Slot 4 (offset 20): K5 Back click
        self.assertEqual(wire[20], int(ButtonType.MOUSE_CLICK))
        self.assertEqual(wire[21], ClickCode.BACK)

        # Slot 5 (offset 24): K4 Forward click
        self.assertEqual(wire[24], int(ButtonType.MOUSE_CLICK))
        self.assertEqual(wire[25], ClickCode.FORWARD)

    def test_k8_fire_and_k9_sniper_bindings(self) -> None:
        self.assertEqual(ACTION_FIRE, 0x17)
        self.assertEqual(ACTION_SNIPER, 0xA6)

        tbl = ButtonTable(profile=1)
        tbl.buttons = [ButtonBinding(i, ButtonType.DISABLED) for i in range(1, 21)]
        # Slot 8 = K8 Fire Key (repeat=5, interval=25ms)
        tbl.buttons[7] = make_fire_binding(8, repeat=5, interval_ms=25)
        # Slot 9 = K9 Sniper (stage=2)
        tbl.buttons[8] = make_sniper_binding(9, stage=2)

        wire = serialize_buttons(tbl)
        parsed = parse_buttons(wire)

        # Check K8
        self.assertEqual(parsed.buttons[7].btype, ButtonType.REPEATED)
        self.assertEqual(parsed.buttons[7].data0, ClickCode.LEFT)
        self.assertEqual(parsed.buttons[7].data1, 5)
        self.assertEqual(parsed.buttons[7].data2, 25)

        # Check K9
        self.assertEqual(parsed.buttons[8].btype, ButtonType.DPI_LOCK)
        self.assertEqual(parsed.buttons[8].data0, 2)


class TestMacroSerializationE2E(unittest.TestCase):
    """Test macro frame serialization, 12-bit delays, and loop modes."""

    def test_macro_12bit_delay_framing(self) -> None:
        m = OnboardMacro(index=1)
        delays = [1, 255, 256, 1000, 4095]
        for d in delays:
            m.events.append(MacroEvent(MacroCmd.KEY_DOWN, 0x04, d))

        buf = serialize_macro(m)
        self.assertEqual(buf[0], 0x04)
        self.assertEqual(buf[1], 0x30)  # Macro command
        self.assertEqual(buf[2], 0x02)  # Write flag
        self.assertEqual(buf[8], 1)  # Slot 1
        self.assertEqual(buf[10], len(delays))

        # Check 12-bit delay framing across byte boundaries
        for i, d in enumerate(delays):
            off = 11 + i * 3
            expected_high = (d >> 8) & 0x0F
            expected_low = d & 0xFF
            self.assertEqual(buf[off] & 0x0F, expected_high)
            self.assertEqual(buf[off + 1], expected_low)

        parsed = parse_macro(buf)
        self.assertEqual([e.delay_ms for e in parsed.events], delays)

    def test_macro_all_event_types(self) -> None:
        m = OnboardMacro(index=2)
        m.events = [
            MacroEvent(MacroCmd.KEY_DOWN, 0x04, 10),
            MacroEvent(MacroCmd.KEY_UP, 0x04, 15),
            MacroEvent(MacroCmd.BTN_DOWN, 0x01, 20),
            MacroEvent(MacroCmd.BTN_UP, 0x01, 25),
            MacroEvent(MacroCmd.WHEEL, 0x01, 30),
            MacroEvent(MacroCmd.MOVE_X, 0x0A, 35),
            MacroEvent(MacroCmd.MOVE_Y, 0xF6, 40),  # -10 signed
        ]
        buf = serialize_macro(m)
        parsed = parse_macro(buf)
        self.assertEqual(len(parsed.events), 7)
        self.assertEqual(parsed.events[0].cmd, MacroCmd.KEY_PRESS)
        self.assertEqual(parsed.events[1].cmd, MacroCmd.KEY_RELEASE)
        self.assertEqual(parsed.events[2].cmd, MacroCmd.BTN_PRESS)
        self.assertEqual(parsed.events[3].cmd, MacroCmd.BTN_RELEASE)
        self.assertEqual(parsed.events[4].cmd, MacroCmd.WHEEL)
        self.assertEqual(parsed.events[5].cmd, MacroCmd.MOVE_X)
        self.assertEqual(parsed.events[6].cmd, MacroCmd.MOVE_Y)

    def test_macro_slot_bounds_and_loop_binding(self) -> None:
        # Slots 1 and 16 valid
        OnboardMacro(index=1)
        OnboardMacro(index=16)
        with self.assertRaises(ValueError):
            serialize_macro(OnboardMacro(index=0))
        with self.assertRaises(ValueError):
            serialize_macro(OnboardMacro(index=17))

        # Max 168 events limit
        m_max = OnboardMacro(index=1)
        m_max.events = [MacroEvent(MacroCmd.KEY_DOWN, 4, 10) for _ in range(MAX_MACRO_EVENTS)]
        buf = serialize_macro(m_max)
        self.assertEqual(buf[10], 168)

        m_overflow = OnboardMacro(index=1)
        m_overflow.events = [MacroEvent(MacroCmd.KEY_DOWN, 4, 10) for _ in range(MAX_MACRO_EVENTS + 1)]
        with self.assertRaises(ValueError):
            serialize_macro(m_overflow)

        # Macro button binding loop modes
        b_loop = make_macro_binding(slot=8, slot_index=3, loop_mode=MacroLoopMode.UNTIL_RELEASE, repeat_count=5)
        self.assertEqual(b_loop.btype, ButtonType.MACRO)
        self.assertEqual(b_loop.data0, 3)
        self.assertEqual(b_loop.data1, 2)
        self.assertEqual(b_loop.data2, 5)


if __name__ == "__main__":
    unittest.main()
