"""Macro persistence and hardware flashing helpers for Icarus GUI.

Manages 16 onboard macro slots, JSON conversion, BKM import, and hardware flashing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from icarus.buttons import (
    PHYSICAL_TO_SLOT,
    ButtonBinding,
    ButtonType,
    ClickCode,
    make_fire_binding,
    make_macro_binding,
    make_multiclick_binding,
    make_multimedia_binding,
    make_sniper_binding,
    make_special_binding,
    parse_buttons,
    serialize_buttons,
)
from icarus.fileconfig import CONFIG_DIR, CONFIG_FILE, load_config_file, save_config_file
from icarus.macros import (
    HID_KEY_MAP,
    NAME_BY_HID,
    MacroCmd,
    MacroEvent,
    MacroLoopMode,
    OnboardMacro,
    serialize_macro,
)
from icarus.protocol import BLOCK_BUTTONS, Device

MACROS_FILE = CONFIG_DIR / "macros.json"

CMD_STR_MAP = {
    "KEY_DOWN": MacroCmd.KEY_DOWN,
    "KEYDOWN": MacroCmd.KEY_DOWN,
    "KEY_PRESS": MacroCmd.KEY_PRESS,
    "KEY_UP": MacroCmd.KEY_UP,
    "KEYUP": MacroCmd.KEY_UP,
    "KEY_RELEASE": MacroCmd.KEY_RELEASE,
    "BTN_DOWN": MacroCmd.BTN_DOWN,
    "BTNDOWN": MacroCmd.BTN_DOWN,
    "BTN_PRESS": MacroCmd.BTN_PRESS,
    "BTN_UP": MacroCmd.BTN_UP,
    "BTNUP": MacroCmd.BTN_UP,
    "BTN_RELEASE": MacroCmd.BTN_RELEASE,
    "WHEEL": MacroCmd.WHEEL,
    "MOVE_X": MacroCmd.MOVE_X,
    "MOVE_Y": MacroCmd.MOVE_Y,
}

BTN_MASK_MAP = {
    "LEFT": 0x01,
    "RIGHT": 0x02,
    "MIDDLE": 0x04,
    "BACK": 0x08,
    "FORWARD": 0x10,
    "1": 0x01,
    "2": 0x02,
    "3": 0x04,
    "4": 0x10,  # Physical forward
    "5": 0x08,  # Physical back
}


def default_macro_slots() -> list[dict[str, Any]]:
    """Generate default 16 empty macro slots."""
    return [
        {
            "id": i,
            "name": f"Macro {i}",
            "loop_mode": "REPEAT_COUNT",
            "repeat_count": 1,
            "events": [],
        }
        for i in range(1, 17)
    ]


def load_macros() -> list[dict[str, Any]]:
    """Load 16 macro slots from macros.json or config.json."""
    if MACROS_FILE.is_file():
        try:
            data = json.loads(MACROS_FILE.read_text())
            if isinstance(data, list) and len(data) == 16:
                return data
        except Exception:
            pass

    if CONFIG_FILE.is_file():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            macros = cfg.get("macros")
            if isinstance(macros, list) and len(macros) == 16:
                return macros
        except Exception:
            pass

    slots = default_macro_slots()
    save_all_macros(slots)
    return slots


def save_all_macros(macros: list[dict[str, Any]]) -> None:
    """Save all 16 macro slots to macros.json and sync into config.json."""
    MACROS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MACROS_FILE.write_text(json.dumps(macros, indent=2))
    if CONFIG_FILE.is_file():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            cfg["macros"] = macros
            CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        except Exception:
            pass


def save_single_macro(macro_data: dict[str, Any]) -> dict[str, Any]:
    """Save or update a single macro slot (1..16)."""
    slot_id = int(macro_data.get("id", 1))
    if not (1 <= slot_id <= 16):
        raise ValueError(f"Macro slot id {slot_id} out of range (1..16)")

    all_macros = load_macros()
    found = False
    for idx, m in enumerate(all_macros):
        if m.get("id") == slot_id:
            all_macros[idx] = {
                "id": slot_id,
                "name": str(macro_data.get("name", f"Macro {slot_id}")),
                "loop_mode": str(macro_data.get("loop_mode", "REPEAT_COUNT")),
                "repeat_count": max(1, min(255, int(macro_data.get("repeat_count", 1)))),
                "events": macro_data.get("events", []),
            }
            found = True
            break

    if not found:
        all_macros.append(macro_data)

    save_all_macros(all_macros)
    return all_macros[slot_id - 1]


def parse_event_code(action_cmd: MacroCmd, raw_code: Any) -> int:
    """Translate raw event code (str or int) to wire byte value."""
    if isinstance(raw_code, int):
        return raw_code & 0xFF

    code_str = str(raw_code).strip()
    if action_cmd in (MacroCmd.KEY_DOWN, MacroCmd.KEY_UP):
        lower = code_str.lower()
        if lower in HID_KEY_MAP:
            return HID_KEY_MAP[lower]
        try:
            return int(code_str, 0) & 0xFF
        except ValueError:
            return 0x04  # Fallback to key 'a'

    if action_cmd in (MacroCmd.BTN_DOWN, MacroCmd.BTN_UP):
        upper = code_str.upper()
        if upper in BTN_MASK_MAP:
            return BTN_MASK_MAP[upper]
        try:
            return int(code_str, 0) & 0xFF
        except ValueError:
            return 0x01  # Left click

    try:
        return int(code_str, 0) & 0xFF
    except ValueError:
        return 0


def flash_macro_to_device(dev: Device, macro_data: dict[str, Any]) -> int:
    """Translate JSON macro into OnboardMacro and flash to hardware."""
    slot_id = int(macro_data.get("id", 1))
    if not (1 <= slot_id <= 16):
        raise ValueError(f"Invalid macro slot index: {slot_id}")

    onboard = OnboardMacro(index=slot_id)
    raw_events = macro_data.get("events", [])

    for ev in raw_events:
        action_name = str(ev.get("action", "KEY_DOWN")).upper()
        cmd = CMD_STR_MAP.get(action_name, MacroCmd.KEY_DOWN)
        code = parse_event_code(cmd, ev.get("code", 0))
        delay = max(1, min(4095, int(ev.get("delay_ms", 15))))
        onboard.events.append(MacroEvent(cmd=cmd, code=code, delay_ms=delay))

    packet = serialize_macro(onboard)
    dev.write_block(packet)
    return len(onboard.events)


def handle_button_bind(dev: Device, req: dict[str, Any]) -> dict[str, Any]:
    """Remap a button K1..K9 on hardware and update config.json."""
    prof_id = int(req.get("profile") or dev.active_profile())
    btn_id = req.get("button", req.get("k", 1))
    if isinstance(btn_id, str) and btn_id.upper().startswith("K"):
        phys_k = int(btn_id[1:])
    else:
        phys_k = int(btn_id)

    if phys_k not in PHYSICAL_TO_SLOT:
        raise ValueError(f"Invalid button K{phys_k} (must be 1..9)")

    slot_idx = PHYSICAL_TO_SLOT[phys_k]  # 1..20
    action = str(req.get("action", "")).lower()

    binding: ButtonBinding
    if action == "fire":
        repeat = int(req.get("repeat", 3))
        interval = int(req.get("interval_ms", req.get("interval", 30)))
        binding = make_fire_binding(slot_idx, repeat=repeat, interval_ms=interval)
    elif action == "sniper":
        stage = int(req.get("stage", 1))
        binding = make_sniper_binding(slot_idx, stage=stage)
    elif action == "macro":
        macro_slot = int(req.get("macro_slot", req.get("macro_id", req.get("slot", 1))))
        loop_mode = int(req.get("loop_mode", 1))
        repeat_count = int(req.get("repeat_count", req.get("repeat", 1)))
        binding = make_macro_binding(slot_idx, macro_slot, loop_mode, repeat_count)
    elif action in ("multimedia", "media"):
        sub_act = str(req.get("sub_action", req.get("media_action", "play_pause")))
        binding = make_multimedia_binding(slot_idx, sub_act)
    elif action == "special":
        sub_act = req.get("sub_action", req.get("special_action", 1))
        binding = make_special_binding(slot_idx, sub_act)
    elif action in ("multiclick", "multi_click", "double_click", "triple_click"):
        cnt = int(req.get("count", 3 if "triple" in action else 2))
        binding = make_multiclick_binding(slot_idx, count=cnt)
    else:
        btype_str = str(req.get("btype", "MOUSE_CLICK")).upper()
        btype = ButtonType[btype_str] if btype_str in ButtonType._member_names_ else ButtonType.MOUSE_CLICK
        data0 = int(req.get("data0", 1))
        data1 = int(req.get("data1", 0))
        data2 = int(req.get("data2", 0))
        binding = ButtonBinding(slot=slot_idx, btype=btype, data0=data0, data1=data1, data2=data2)

    # Read current button block from hardware
    raw_btns = dev.read_block(prof_id, BLOCK_BUTTONS)
    tbl = parse_buttons(raw_btns)
    tbl.buttons[slot_idx - 1] = binding

    # Commit to hardware
    dev.write_block(serialize_buttons(tbl))

    # Update config.json
    try:
        cfg = load_config_file()
        p_str = str(prof_id)
        if "profiles" in cfg and p_str in cfg["profiles"]:
            cfg["profiles"][p_str]["buttons"][f"K{phys_k}"] = {
                "summary": binding.summary(),
                "btype": binding.btype.name,
                "data0": binding.data0,
                "data1": binding.data1,
                "data2": binding.data2,
            }
            save_config_file(cfg)
    except Exception:
        pass

    return {
        "success": True,
        "profile": prof_id,
        "button": f"K{phys_k}",
        "summary": binding.summary(),
        "btype": binding.btype.name,
        "data0": binding.data0,
        "data1": binding.data1,
        "data2": binding.data2,
    }
