"""Human & AI-Agent editable single-file declarative JSON configuration.

Manages ~/.config/icarus/config.json:
- `pull_from_mouse`: reads mouse hardware memory and dumps clean JSON.
- `apply_to_mouse`: parses JSON, validates values, and flashes to mouse hardware.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from icarus.buttons import (
    PHYSICAL_TO_SLOT,
    ButtonBinding,
    ButtonTable,
    ButtonType,
    ClickCode,
    DpiSwitchCode,
    parse_buttons,
    serialize_buttons,
)
from icarus.config import (
    DpiStage,
    MouseConfig,
    RgbEffect,
    parse_config,
    serialize_config,
)
from icarus.protocol import BLOCK_BUTTONS, BLOCK_CONFIG, Device
from icarus.scroll import get_scroll_factor, set_scroll_factor

CONFIG_DIR = Path.home() / ".config" / "icarus"
CONFIG_FILE = CONFIG_DIR / "config.json"


def color_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def hex_to_color(h: str) -> tuple[int, int, int]:
    s = h.lstrip("#")
    if len(s) != 6:
        return (255, 0, 0)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def mouse_to_dict(dev: Device) -> dict[str, Any]:
    """Read all hardware profiles and build a clean declarative dictionary."""
    act_p = dev.active_profile()
    data: dict[str, Any] = {
        "active_profile": act_p,
        "scroll_factor": get_scroll_factor(),
        "profiles": {},
    }

    for p in (1, 2):
        cfg_bytes = dev.read_block(p, BLOCK_CONFIG)
        cfg = parse_config(cfg_bytes)
        btn_bytes = dev.read_block(p, BLOCK_BUTTONS)
        tbl = parse_buttons(btn_bytes)

        prof_dict: dict[str, Any] = {
            "name": f"Profile {p}",
            "channel_order": getattr(cfg, "channel_order", "RGB"),
            "polling_rate_hz": cfg.polling_rate,
            "lod": "3mm" if cfg.lod == 1 else "2mm",
            "active_dpi_stage": cfg.active_dpi_stage,
            "dpi_stages": [
                {
                    "stage": idx + 1,
                    "dpi": s.dpi,
                    "color": color_to_hex(s.color),
                    "enabled": s.enabled,
                }
                for idx, s in enumerate(cfg.dpi_stages)
            ],
            "rgb": {
                "effect": cfg.rgb_effect.name,
                "brightness": cfg.rgb_brightness,
                "speed": cfg.rgb_speed,
                "direction": cfg.rgb_direction,
                "single_color": color_to_hex(cfg.single_color),
                "breathing_colors": [color_to_hex(c) for c in cfg.breathing_colors],
                "zone_colors": [color_to_hex(c) for c in cfg.zone_colors],
                "flicker_colors": [color_to_hex(c) for c in cfg.flicker_colors],
            },
            "buttons": {
                f"K{k}": {
                    "summary": tbl.buttons[PHYSICAL_TO_SLOT[k] - 1].summary(),
                    "btype": tbl.buttons[PHYSICAL_TO_SLOT[k] - 1].btype.name,
                    "data0": tbl.buttons[PHYSICAL_TO_SLOT[k] - 1].data0,
                    "data1": tbl.buttons[PHYSICAL_TO_SLOT[k] - 1].data1,
                    "data2": tbl.buttons[PHYSICAL_TO_SLOT[k] - 1].data2,
                }
                for k in range(1, 10)
            },
        }
        data["profiles"][str(p)] = prof_dict

    return data


def save_config_file(data: dict[str, Any], path: Path = CONFIG_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    return path


def load_config_file(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found. Run 'icarus pull' first.")
    return json.loads(path.read_text())


def pull_from_mouse(dev: Device, path: Path = CONFIG_FILE) -> Path:
    """Pull hardware settings from mouse and save to JSON."""
    d = mouse_to_dict(dev)
    return save_config_file(d, path)


def apply_to_mouse(dev: Device, path: Path = CONFIG_FILE) -> list[str]:
    """Read JSON configuration and flash to mouse hardware memory."""
    d = load_config_file(path)
    logs: list[str] = []

    # 1. Update active profile
    act_p = d.get("active_profile", 1)
    if act_p in (1, 2):
        dev.set_active_profile(act_p)
        logs.append(f"Set active profile to {act_p}")

    if "scroll_factor" in d:
        try:
            set_scroll_factor(float(d["scroll_factor"]))
            logs.append(f"Applied scroll factor: {d['scroll_factor']}")
        except Exception:
            pass

    profiles = d.get("profiles", {})
    for p_str, p_data in profiles.items():
        try:
            p_id = int(p_str)
        except ValueError:
            continue
        if p_id not in (1, 2):
            continue

        # Read current block to preserve calibration
        ch_order = p_data.get("channel_order", d.get("channel_order", "RGB"))
        cfg = parse_config(dev.read_block(p_id, BLOCK_CONFIG), channel_order=ch_order)
        cfg.channel_order = ch_order
        if "polling_rate_hz" in p_data:
            cfg.polling_rate = p_data["polling_rate_hz"]
        if "lod" in p_data:
            cfg.lod = 1 if p_data["lod"] in ("3mm", "high", "High", 1) else 0
        if "active_dpi_stage" in p_data:
            cfg.active_dpi_stage = max(1, min(8, p_data["active_dpi_stage"]))

        if "dpi_stages" in p_data:
            for s_info in p_data["dpi_stages"]:
                idx = s_info.get("stage", 1) - 1
                if 0 <= idx < len(cfg.dpi_stages):
                    if "dpi" in s_info:
                        cfg.dpi_stages[idx].dpi = s_info["dpi"]
                    if "color" in s_info:
                        cfg.dpi_stages[idx].color = hex_to_color(s_info["color"])
                    if "enabled" in s_info:
                        cfg.dpi_stages[idx].enabled = bool(s_info["enabled"])

        rgb = p_data.get("rgb", {})
        if "effect" in rgb:
            eff_name = rgb["effect"].upper()
            if eff_name in RgbEffect._member_names_:
                cfg.rgb_effect = RgbEffect[eff_name]
        if "brightness" in rgb:
            cfg.rgb_brightness = max(1, min(4, rgb["brightness"]))
        if "speed" in rgb:
            cfg.rgb_speed = max(1, min(3, rgb["speed"]))
        if "direction" in rgb:
            cfg.rgb_direction = 1 if rgb["direction"] in (1, "1", "backward", "back") else 0
        if "single_color" in rgb:
            cfg.single_color = hex_to_color(rgb["single_color"])
        if "breathing_colors" in rgb:
            cfg.breathing_colors = [hex_to_color(c) for c in rgb["breathing_colors"]]
        if "zone_colors" in rgb:
            cfg.zone_colors = [hex_to_color(c) for c in rgb["zone_colors"]]
        if "flicker_colors" in rgb:
            cfg.flicker_colors = [hex_to_color(c) for c in rgb["flicker_colors"]]

        # Write config block
        dev.write_block(serialize_config(cfg))
        logs.append(f"Committed config block for Profile {p_id}")

        # Update buttons if specified
        if "buttons" in p_data:
            tbl = parse_buttons(dev.read_block(p_id, BLOCK_BUTTONS))
            for k_name, b_info in p_data["buttons"].items():
                if k_name.startswith("K"):
                    try:
                        k_num = int(k_name[1:])
                    except ValueError:
                        continue
                    if k_num in PHYSICAL_TO_SLOT:
                        slot_idx = PHYSICAL_TO_SLOT[k_num] - 1
                        if 0 <= slot_idx < len(tbl.buttons):
                            btype_str = b_info.get("btype", "")
                            if btype_str in ButtonType._member_names_:
                                tbl.buttons[slot_idx].btype = ButtonType[btype_str]
                                tbl.buttons[slot_idx].data0 = b_info.get("data0", 0)
                                tbl.buttons[slot_idx].data1 = b_info.get("data1", 0)
                                tbl.buttons[slot_idx].data2 = b_info.get("data2", 0)
            dev.write_block(serialize_buttons(tbl))
            logs.append(f"Committed button block for Profile {p_id}")

    return logs
