"""Comprehensive unit tests for all 20 button slots (K1..K20), bindings, and wire formats."""

from __future__ import annotations

import unittest
from pathlib import Path

from icarus.buttons import (
    BUTTON_NAMES,
    BUTTON_WRITE_MAGIC,
    MULTIMEDIA_ACTIONS,
    MULTIMEDIA_NAMES,
    PHYSICAL_TO_SLOT,
    REPORT_DATA,
    SLOT_TO_PHYSICAL,
    SPECIAL_HW_ACTIONS,
    SPECIAL_HW_NAMES,
    ButtonBinding,
    ButtonTable,
    ButtonType,
    ClickCode,
    DpiSwitchCode,
    MultiClickCode,
    make_fire_binding,
    make_macro_binding,
    make_multiclick_binding,
    make_multimedia_binding,
    make_sniper_binding,
    make_special_binding,
    parse_buttons,
    serialize_buttons,
)


class TestButtonsK20(unittest.TestCase):
    """Test suite covering all 20 button slots, mappings, bindings, and serialization."""

    def test_physical_to_slot_and_slot_to_physical_bijection(self) -> None:
        """Verify 1-to-1 bijection for all 20 slots and specific hardware pin swap."""
        self.assertEqual(len(PHYSICAL_TO_SLOT), 20)
        self.assertEqual(len(SLOT_TO_PHYSICAL), 20)

        # Hardware wiring pin swap: K4 <-> Slot 5, K5 <-> Slot 4
        self.assertEqual(PHYSICAL_TO_SLOT[4], 5, "Physical K4 must map to hardware Slot 5 (Pin 5)")
        self.assertEqual(PHYSICAL_TO_SLOT[5], 4, "Physical K5 must map to hardware Slot 4 (Pin 4)")
        self.assertEqual(SLOT_TO_PHYSICAL[5], 4, "Hardware Slot 5 must map to physical K4")
        self.assertEqual(SLOT_TO_PHYSICAL[4], 5, "Hardware Slot 4 must map to physical K5")

        # Identity for all other slots
        for k in range(1, 21):
            if k not in (4, 5):
                self.assertEqual(PHYSICAL_TO_SLOT[k], k)
                self.assertEqual(SLOT_TO_PHYSICAL[k], k)

            # Roundtrip mapping bijection
            slot = PHYSICAL_TO_SLOT[k]
            phys = SLOT_TO_PHYSICAL[slot]
            self.assertEqual(phys, k, f"Roundtrip slot mapping failed for button {k}")

    def test_button_names_k1_through_k20(self) -> None:
        """Verify all 20 physical buttons have valid descriptive labels."""
        self.assertEqual(len(BUTTON_NAMES), 20)
        for k in range(1, 21):
            self.assertIn(k, BUTTON_NAMES)
            self.assertTrue(BUTTON_NAMES[k].startswith(f"K{k} "))

        self.assertIn("Left Click", BUTTON_NAMES[1])
        self.assertIn("Right Click", BUTTON_NAMES[2])
        self.assertIn("Middle Click", BUTTON_NAMES[3])
        self.assertIn("Forward", BUTTON_NAMES[4])
        self.assertIn("Back", BUTTON_NAMES[5])
        self.assertIn("DPI Up", BUTTON_NAMES[6])
        self.assertIn("DPI Down", BUTTON_NAMES[7])
        self.assertIn("Fire Key", BUTTON_NAMES[8])
        self.assertIn("Sniper", BUTTON_NAMES[9])
        for k in range(10, 21):
            self.assertIn(f"Extended Slot {k}", BUTTON_NAMES[k])

    def test_button_binding_properties_all_slots(self) -> None:
        """Verify ButtonBinding properties (physical_button, name) across slots 1..20."""
        for slot in range(1, 21):
            b = ButtonBinding(slot=slot, btype=ButtonType.MOUSE_CLICK, data0=ClickCode.LEFT)
            phys = SLOT_TO_PHYSICAL[slot]
            self.assertEqual(b.physical_button, phys)
            self.assertEqual(b.name, BUTTON_NAMES[phys])

    def test_summary_formatting_for_all_types(self) -> None:
        """Verify human-readable summary string generation for every ButtonType."""
        # MOUSE_CLICK
        self.assertEqual(ButtonBinding(1, ButtonType.MOUSE_CLICK, ClickCode.LEFT).summary(), "Left Click")
        self.assertEqual(ButtonBinding(2, ButtonType.MOUSE_CLICK, ClickCode.RIGHT).summary(), "Right Click")
        self.assertEqual(ButtonBinding(3, ButtonType.MOUSE_CLICK, ClickCode.MIDDLE).summary(), "Middle Click")
        self.assertEqual(ButtonBinding(4, ButtonType.MOUSE_CLICK, ClickCode.BACK).summary(), "Back")
        self.assertEqual(ButtonBinding(5, ButtonType.MOUSE_CLICK, ClickCode.FORWARD).summary(), "Forward")

        # DPI_SWITCH
        self.assertEqual(ButtonBinding(7, ButtonType.DPI_SWITCH, DpiSwitchCode.CYCLE).summary(), "DPI Cycle")
        self.assertEqual(ButtonBinding(7, ButtonType.DPI_SWITCH, DpiSwitchCode.UP).summary(), "DPI +")
        self.assertEqual(ButtonBinding(7, ButtonType.DPI_SWITCH, DpiSwitchCode.DOWN).summary(), "DPI -")

        # DPI_LOCK / SNIPER
        self.assertEqual(ButtonBinding(8, ButtonType.DPI_LOCK, 2).summary(), "Sniper / DPI Lock (stage=2)")
        self.assertEqual(ButtonBinding(8, ButtonType.SNIPER, 0).summary(), "Sniper / DPI Lock (stage=1)")

        # REPEATED / FIRE
        self.assertEqual(
            ButtonBinding(9, ButtonType.REPEATED, 1, 5, 25).summary(),
            "Fire Key (burst, repeat=5, interval=25ms)",
        )

        # KEY with combinations of modifiers
        self.assertEqual(ButtonBinding(10, ButtonType.KEY, 0x00, 0x04).summary(), "HID(0x04)")
        self.assertEqual(ButtonBinding(10, ButtonType.KEY, 0x01, 0x06).summary(), "Ctrl+HID(0x06)")
        self.assertEqual(ButtonBinding(10, ButtonType.KEY, 0x03, 0x06).summary(), "Ctrl+Shift+HID(0x06)")
        self.assertEqual(ButtonBinding(10, ButtonType.KEY, 0x0F, 0x06).summary(), "Ctrl+Shift+Alt+Super+HID(0x06)")

        # MACRO
        self.assertEqual(ButtonBinding(11, ButtonType.MACRO, 3, 1, 10).summary(), "Macro #3 (REPEAT_COUNT, count=10)")
        self.assertEqual(ButtonBinding(11, ButtonType.MACRO, 4, 2, 1).summary(), "Macro #4 (UNTIL_RELEASE, count=1)")
        self.assertEqual(ButtonBinding(11, ButtonType.MACRO, 5, 4, 1).summary(), "Macro #5 (UNTIL_ANY_KEY, count=1)")

        # MULTI_CLICK
        self.assertEqual(ButtonBinding(12, ButtonType.MULTI_CLICK, MultiClickCode.DOUBLE).summary(), "Double Click")
        self.assertEqual(ButtonBinding(12, ButtonType.MULTI_CLICK, MultiClickCode.TRIPLE).summary(), "Triple Click")

        # DISABLED
        self.assertEqual(ButtonBinding(13, ButtonType.DISABLED).summary(), "Disabled")

    def test_all_18_multimedia_actions(self) -> None:
        """Verify all 18 multimedia actions in MULTIMEDIA_ACTIONS create valid bindings."""
        for action_name, expected_tuple in MULTIMEDIA_ACTIONS.items():
            b = make_multimedia_binding(slot_or_cat=10, action_or_code=action_name)
            self.assertEqual(b.slot, 10)
            self.assertEqual(b.btype, ButtonType.MULTIMEDIA)
            self.assertEqual((b.data0, b.data1, b.data2), expected_tuple)
            self.assertEqual(b.summary(), MULTIMEDIA_NAMES[expected_tuple])

        # Test tuple input
        b_tup = make_multimedia_binding(11, (0x40, 0x00, 0x00))
        self.assertEqual((b_tup.data0, b_tup.data1, b_tup.data2), (0x40, 0x00, 0x00))

        # Test (category, code) signature: cat=0, code=0x10 -> data0=0x10
        b_cat0 = make_multimedia_binding(12, 0, 0x10)
        self.assertEqual((b_cat0.data0, b_cat0.data1, b_cat0.data2), (0x10, 0x00, 0x00))

        # Test (category, code) signature: cat=1, code=0x20 -> data1=0x20
        b_cat1 = make_multimedia_binding(13, 1, 0x20)
        self.assertEqual((b_cat1.data0, b_cat1.data1, b_cat1.data2), (0x00, 0x20, 0x00))

        # Test (category, code) signature: cat=2, code=0x08 -> data2=0x08
        b_cat2 = make_multimedia_binding(14, 2, 0x08)
        self.assertEqual((b_cat2.data0, b_cat2.data1, b_cat2.data2), (0x00, 0x00, 0x08))

    def test_all_7_special_hardware_actions(self) -> None:
        """Verify all 7 special hardware actions create valid bindings."""
        for action_name, expected_code in SPECIAL_HW_ACTIONS.items():
            b = make_special_binding(slot_or_code=15, action=action_name)
            self.assertEqual(b.slot, 15)
            self.assertEqual(b.btype, ButtonType.SPECIAL)
            self.assertEqual(b.data0, expected_code)
            self.assertEqual(b.summary(), SPECIAL_HW_NAMES[expected_code])

        # Test integer code constructor
        b_code = make_special_binding(slot_or_code=0x04)
        self.assertEqual(b_code.data0, 0x04)

        # Test string constructor with default slot
        b_str = make_special_binding(slot_or_code="lighting_toggle")
        self.assertEqual(b_str.data0, 0x04)

    def test_helper_constructors_bounds(self) -> None:
        """Test fire, sniper, multiclick, and macro constructors with boundary values."""
        # Fire key bounds (repeat 1..255, interval 5..255)
        b_fire = make_fire_binding(8, repeat=0, interval_ms=1)
        self.assertEqual(b_fire.data1, 1)
        self.assertEqual(b_fire.data2, 5)

        b_fire_max = make_fire_binding(8, repeat=300, interval_ms=500)
        self.assertEqual(b_fire_max.data1, 255)
        self.assertEqual(b_fire_max.data2, 255)

        # Sniper bounds (stage 1..8)
        b_sniper_min = make_sniper_binding(9, stage=0)
        self.assertEqual(b_sniper_min.data0, 1)

        b_sniper_max = make_sniper_binding(9, stage=12)
        self.assertEqual(b_sniper_max.data0, 8)

        # Multi-click
        b_mc_2 = make_multiclick_binding(10, count=2)
        self.assertEqual(b_mc_2.data0, int(MultiClickCode.DOUBLE))
        b_mc_3 = make_multiclick_binding(10, count=3)
        self.assertEqual(b_mc_3.data0, int(MultiClickCode.TRIPLE))

        # Macro bounds (slot_index 1..16, repeat_count 1..255)
        b_mac = make_macro_binding(16, slot_index=0, loop_mode=1, repeat_count=0)
        self.assertEqual(b_mac.data0, 1)
        self.assertEqual(b_mac.data2, 1)

        b_mac_max = make_macro_binding(16, slot_index=20, loop_mode=2, repeat_count=500)
        self.assertEqual(b_mac_max.data0, 16)
        self.assertEqual(b_mac_max.data2, 255)

    def test_roundtrip_all_20_button_slots(self) -> None:
        """Configure and serialize all 20 slots, then parse and verify exact roundtrip."""
        bindings: list[ButtonBinding] = [
            ButtonBinding(1, ButtonType.MOUSE_CLICK, ClickCode.LEFT),
            ButtonBinding(2, ButtonType.MOUSE_CLICK, ClickCode.RIGHT),
            ButtonBinding(3, ButtonType.MOUSE_CLICK, ClickCode.MIDDLE),
            ButtonBinding(4, ButtonType.MOUSE_CLICK, ClickCode.BACK),
            ButtonBinding(5, ButtonType.MOUSE_CLICK, ClickCode.FORWARD),
            ButtonBinding(6, ButtonType.DPI_SWITCH, DpiSwitchCode.UP),
            ButtonBinding(7, ButtonType.DPI_SWITCH, DpiSwitchCode.DOWN),
            ButtonBinding(8, ButtonType.REPEATED, ClickCode.LEFT, 3, 30),
            ButtonBinding(9, ButtonType.DPI_LOCK, 1),
            ButtonBinding(10, ButtonType.MULTI_CLICK, MultiClickCode.DOUBLE),
            ButtonBinding(11, ButtonType.MULTIMEDIA, 0x10, 0x00, 0x00),  # Mute
            ButtonBinding(12, ButtonType.MULTIMEDIA, 0x40, 0x00, 0x00),  # Volume Up
            ButtonBinding(13, ButtonType.SPECIAL, 0x01),  # Profile switch
            ButtonBinding(14, ButtonType.SPECIAL, 0x04),  # Lighting toggle
            ButtonBinding(15, ButtonType.KEY, 0x01, 0x06),  # Ctrl+C
            ButtonBinding(16, ButtonType.MACRO, 1, 1, 5),
            ButtonBinding(17, ButtonType.DISABLED),
            ButtonBinding(18, ButtonType.MULTIMEDIA, 0x08, 0x00, 0x00),  # Play/Pause
            ButtonBinding(19, ButtonType.DPI_SWITCH, DpiSwitchCode.CYCLE),
            ButtonBinding(20, ButtonType.SPECIAL, 0x02),  # Polling rate switch
        ]

        table = ButtonTable(profile=1, buttons=bindings)
        wire_data = serialize_buttons(table)

        self.assertEqual(len(wire_data), 520)
        self.assertEqual(wire_data[0], REPORT_DATA)  # 0x04
        self.assertEqual(wire_data[1], 0x12)  # Profile 1 Button Block command (0x12)
        self.assertEqual(wire_data[3], BUTTON_WRITE_MAGIC)  # 0x50

        parsed = parse_buttons(wire_data)
        self.assertEqual(parsed.profile, 1)
        self.assertEqual(len(parsed.buttons), 20)

        for i in range(20):
            orig = bindings[i]
            res = parsed.buttons[i]
            self.assertEqual(res.slot, orig.slot, f"Slot mismatch at index {i}")
            self.assertEqual(res.btype, orig.btype, f"Type mismatch at slot {orig.slot}")
            self.assertEqual(res.data0, orig.data0, f"data0 mismatch at slot {orig.slot}")
            self.assertEqual(res.data1, orig.data1, f"data1 mismatch at slot {orig.slot}")
            self.assertEqual(res.data2, orig.data2, f"data2 mismatch at slot {orig.slot}")

    def test_parse_buttons_invalid_inputs(self) -> None:
        """Verify parse_buttons raises ValueError on invalid buffer length or headers."""
        # Too short (< 88 bytes)
        with self.assertRaises(ValueError):
            parse_buttons(bytes(87))

        # Wrong report ID
        buf_bad_report = bytearray(520)
        buf_bad_report[0] = 0x05  # Should be 0x04
        buf_bad_report[1] = 0x12
        with self.assertRaises(ValueError):
            parse_buttons(bytes(buf_bad_report))

        # Invalid profile ID (e.g., Profile 3 or Profile 0)
        buf_bad_profile = bytearray(520)
        buf_bad_profile[0] = 0x04
        buf_bad_profile[1] = 0x32  # Profile 3
        with self.assertRaises(ValueError):
            parse_buttons(bytes(buf_bad_profile))


if __name__ == "__main__":
    unittest.main()
