"""Scroll wheel speed and sensitivity management for Icarus gaming mouse.

Provides OS-level scroll factor query and modification via Hyprland/Omarchy
IPC and persistent configuration in ~/.config/hypr/input.lua.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

HYPR_INPUT_LUA = Path.home() / ".config" / "hypr" / "input.lua"
DEVICE_NAME = "sinowealth-wired-gaming-mouse"


def get_scroll_factor() -> float:
    """Retrieve the current scroll factor for the Sinowealth gaming mouse."""
    try:
        res = subprocess.run(
            ["hyprctl", "devices", "-j"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            for mouse in data.get("mice", []):
                if mouse.get("name") == DEVICE_NAME:
                    factor = float(mouse.get("scrollFactor", -1.0))
                    if factor > 0:
                        return round(factor, 2)
    except Exception:
        pass

    # Fallback to inspecting input.lua
    if HYPR_INPUT_LUA.exists():
        try:
            content = HYPR_INPUT_LUA.read_text(encoding="utf-8")
            match = re.search(r'name\s*=\s*"' + re.escape(DEVICE_NAME) + r'"[^}]*?scroll_factor\s*=\s*([0-9.]+)', content, re.DOTALL)
            if match:
                return round(float(match.group(1)), 2)
        except Exception:
            pass

    return 1.0


def set_scroll_factor(factor: float, config_path: Path = HYPR_INPUT_LUA) -> bool:
    """Set the scroll speed factor dynamically and persist in input.lua."""
    factor = round(max(0.1, min(20.0, float(factor))), 2)

    # 1. Apply runtime via Hyprland eval
    try:
        lua_code = f'hl.device({{ name = "{DEVICE_NAME}", scroll_factor = {factor} }})'
        subprocess.run(
            ["hyprctl", "eval", lua_code],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except Exception:
        pass

    # 2. Persist to ~/.config/hypr/input.lua if it exists
    if config_path.exists():
        try:
            content = config_path.read_text(encoding="utf-8")
            pattern = r'(hl\.device\(\{\s*name\s*=\s*"' + re.escape(DEVICE_NAME) + r'",)(.*?)(^\}\))'
            m = re.search(pattern, content, re.DOTALL | re.MULTILINE)
            if m:
                body = m.group(2)
                if "scroll_factor" in body:
                    body = re.sub(r'scroll_factor\s*=\s*[0-9.]+,?', f'scroll_factor = {factor},', body)
                else:
                    body = body.rstrip() + f'\n  scroll_factor = {factor},\n'
                new_block = f"{m.group(1)}{body}{m.group(3)}"
                new_content = content[:m.start()] + new_block + content[m.end():]
                config_path.write_text(new_content, encoding="utf-8")
            else:
                # Append dedicated device block, strictly preserving touchpad and other config
                device_block = (
                    f'\nhl.device({{\n'
                    f'  name = "{DEVICE_NAME}",\n'
                    f'  sensitivity = 0.0,\n'
                    f'  accel_profile = "flat",\n'
                    f'  natural_scroll = false,\n'
                    f'  scroll_factor = {factor},\n'
                    f'}})\n'
                )
                config_path.write_text(content.rstrip() + "\n" + device_block, encoding="utf-8")
        except Exception:
            pass

    return True
