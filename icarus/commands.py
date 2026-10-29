"""CLI command handlers for Icarus."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from icarus import bkm
from icarus.buttons import (
    BUTTON_NAMES,
    PHYSICAL_TO_SLOT,
    SLOT_TO_PHYSICAL,
    ButtonType,
    ClickCode,
    DpiSwitchCode,
    parse_buttons,
    serialize_buttons,
)
from icarus.config import (
    VALID_DPIS,
    RgbEffect,
    parse_config,
    serialize_config,
)
from icarus.fileconfig import CONFIG_FILE, apply_to_mouse, pull_from_mouse
from icarus.hidraw import Hidraw, find_vendor_node
from icarus.macros import HID_KEY_MAP, OnboardMacro, serialize_macro
from icarus.protocol import BLOCK_BUTTONS, BLOCK_CONFIG, Device

STATE_DIR = Path.home() / ".local" / "state" / "icarusctl"
ALT_STATE_DIR = Path.home() / ".local" / "state" / "icarus"


def ensure_backup(dev: Device) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = STATE_DIR / f"backup_{ts}"
    for d in (STATE_DIR, ALT_STATE_DIR):
        (d / f"backup_{ts}").mkdir(parents=True, exist_ok=True)
    for p in (1, 2):
        b1 = dev.read_block(p, BLOCK_CONFIG)
        b2 = dev.read_block(p, BLOCK_BUTTONS)
        (out_dir / f"p{p}_b1.bin").write_bytes(b1)
        (out_dir / f"p{p}_b2.bin").write_bytes(b2)
        (ALT_STATE_DIR / f"backup_{ts}" / f"p{p}_b1.bin").write_bytes(b1)
        (ALT_STATE_DIR / f"backup_{ts}" / f"p{p}_b2.bin").write_bytes(b2)
    return out_dir


def cmd_gui(args: argparse.Namespace) -> int:
    from icarus.gui import run_gui
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8421)
    no_browser = getattr(args, "no_browser", False)
    run_gui(host=host, port=port, open_browser=not no_browser)
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        target = Path(args.path) if getattr(args, "path", None) else CONFIG_FILE
        saved = pull_from_mouse(dev, target)
        print(f"Pulled mouse hardware configuration into: {saved}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        target = Path(args.path) if getattr(args, "path", None) else CONFIG_FILE
        logs = apply_to_mouse(dev, target)
        for log in logs:
            print(f"  {log}")
        print("Applied configuration file to mouse hardware.")
    return 0


def cmd_import_bkm(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        bkm_path = Path(args.file)
        if not bkm_path.is_file():
            print(f"Error: file not found: {bkm_path}", file=sys.stderr)
            return 1
        prof = bkm.parse_bkm_file(bkm_path)
        print(f"Parsed {bkm_path.name}: {len(prof.macros)} macros decrypted with TEA.")
        for m in prof.macros:
            print(f"  Macro #{m.index} '{m.name}': {len(m.events)} events")
        logs = bkm.import_bkm_to_mouse(dev, prof, target_profile=args.profile)
        for l in logs:
            print(f"  {l}")
        print(f"Successfully imported {bkm_path.name} into Profile {args.profile}!")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        psd = dev.read_psd()
        act_p = dev.active_profile()
        print("Device: Gamepower Icarus (258a:0027)")
        print(f"Firmware PSD: {psd}")
        print(f"Active Profile: {act_p}")

        cfg_bytes = dev.read_block(act_p, BLOCK_CONFIG)
        cfg = parse_config(cfg_bytes)
        print(f"\n[Profile {act_p} Settings]")
        print(f"  Polling Rate : {cfg.polling_rate} Hz")
        lod_str = "High (3mm)" if cfg.lod == 1 else "Low (2mm)"
        print(f"  LOD          : {lod_str}")
        print(
            f"  RGB Lighting : {cfg.rgb_effect.name} "
            f"(Brightness: {cfg.rgb_brightness}/4, Speed: {cfg.rgb_speed}/3)"
        )
        print(f"  Active DPI   : Stage {cfg.active_dpi_stage} ({cfg.dpi_stages[cfg.active_dpi_stage-1].dpi} DPI)")
        print("  DPI Stages   :")
        for idx, stage in enumerate(cfg.dpi_stages, 1):
            marker = "*" if idx == cfg.active_dpi_stage else " "
            en_str = "enabled" if stage.enabled else "disabled"
            rgb = f"RGB({stage.color[0]},{stage.color[1]},{stage.color[2]})"
            print(f"   {marker} Stage {idx}: {stage.dpi:5d} DPI  [{rgb:15s}] ({en_str})")

        btn_bytes = dev.read_block(act_p, BLOCK_BUTTONS)
        tbl = parse_buttons(btn_bytes)
        print(f"\n[Button Mapping (Profile {act_p})]")
        for k in range(1, 10):
            hw_slot = PHYSICAL_TO_SLOT[k]
            b = tbl.buttons[hw_slot - 1]
            print(f"  {BUTTON_NAMES[k]:24s} -> {b.summary()}")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        dev.set_active_profile(args.id)
        time.sleep(0.05)
        print(f"Active profile set to: {dev.active_profile()}")
    return 0


def cmd_rate(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        act_p = dev.active_profile()
        cfg = parse_config(dev.read_block(act_p, BLOCK_CONFIG))
        cfg.polling_rate = args.hz
        dev.write_block(serialize_config(cfg))
        print(f"Profile {act_p} polling rate set to: {args.hz} Hz")
    return 0


def cmd_dpi(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        if args.val not in VALID_DPIS:
            closest = min(VALID_DPIS, key=lambda d: abs(d - args.val))
            print(
                f"Error: {args.val} DPI is invalid for PMW3325. Valid steps: 400..5000 (step 100), 5500..10000 (step 500). Closest: {closest}",
                file=sys.stderr,
            )
            return 1
        ensure_backup(dev)
        act_p = dev.active_profile()
        cfg = parse_config(dev.read_block(act_p, BLOCK_CONFIG))
        stage_idx = args.stage - 1
        cfg.dpi_stages[stage_idx].dpi = args.val
        if args.color:
            r, g, b = [int(x) for x in args.color.split(",")]
            cfg.dpi_stages[stage_idx].color = (r, g, b)
        dev.write_block(serialize_config(cfg))
        print(f"Profile {act_p} stage {args.stage} set to {args.val} DPI")
    return 0


def cmd_dpi_stage(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        act_p = dev.active_profile()
        cfg = parse_config(dev.read_block(act_p, BLOCK_CONFIG))
        cfg.active_dpi_stage = args.stage
        dev.write_block(serialize_config(cfg))
        print(f"Profile {act_p} active DPI stage set to: {args.stage}")
    return 0


def cmd_lod(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        act_p = dev.active_profile()
        cfg = parse_config(dev.read_block(act_p, BLOCK_CONFIG))
        cfg.lod = 1 if args.mode.lower() in ("high", "3mm", "1") else 0
        dev.write_block(serialize_config(cfg))
        lod_str = "High (3mm)" if cfg.lod == 1 else "Low (2mm)"
        print(f"Profile {act_p} LOD set to: {lod_str}")
    return 0


def _parse_colors(s: str) -> list[tuple[int, int, int]]:
    res = []
    for p in s.replace(";", " ").replace("|", " ").split():
        parts = [int(x) for x in p.split(",") if x.strip()]
        if len(parts) == 3:
            res.append((parts[0], parts[1], parts[2]))
    return res


def cmd_led(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        act_p = dev.active_profile()
        cfg = parse_config(dev.read_block(act_p, BLOCK_CONFIG))
        eff_upper = args.effect.upper()
        if eff_upper not in RgbEffect._member_names_:
            names = ", ".join(e.name.lower() for e in RgbEffect)
            print(f"Unknown effect: {args.effect}. Available: {names}")
            return 1
        cfg.rgb_effect = RgbEffect[eff_upper]
        if args.brightness is not None:
            cfg.rgb_brightness = max(1, min(4, args.brightness))
        if args.speed is not None:
            cfg.rgb_speed = max(1, min(3, args.speed))
        if getattr(args, "direction", None) is not None:
            cfg.rgb_direction = 1 if str(args.direction).lower() in ("1", "backward", "back") else 0
        if getattr(args, "color", None):
            r, g, b = [int(x) for x in args.color.split(",")]
            cfg.single_color = (r, g, b)
        if getattr(args, "flicker_colors", None):
            cfg.flicker_colors = _parse_colors(args.flicker_colors)
        if getattr(args, "zone_colors", None):
            cfg.zone_colors = _parse_colors(args.zone_colors)
        if getattr(args, "breathing_colors", None):
            cfg.breathing_colors = _parse_colors(args.breathing_colors)
        dev.write_block(serialize_config(cfg))
        print(f"Profile {act_p} RGB effect: {cfg.rgb_effect.name}")
    return 0


def cmd_bind(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        act_p = dev.active_profile()
        tbl = parse_buttons(dev.read_block(act_p, BLOCK_BUTTONS))
        phys_k = args.slot
        hw_slot = PHYSICAL_TO_SLOT.get(phys_k, phys_k)
        b = tbl.buttons[hw_slot - 1]
        action = args.action.lower()
        if action == "left":
            b.btype, b.data0 = ButtonType.MOUSE_CLICK, ClickCode.LEFT
        elif action == "right":
            b.btype, b.data0 = ButtonType.MOUSE_CLICK, ClickCode.RIGHT
        elif action == "middle":
            b.btype, b.data0 = ButtonType.MOUSE_CLICK, ClickCode.MIDDLE
        elif action == "back":
            b.btype, b.data0 = ButtonType.MOUSE_CLICK, ClickCode.BACK
        elif action == "forward":
            b.btype, b.data0 = ButtonType.MOUSE_CLICK, ClickCode.FORWARD
        elif action in ("dpi+", "dpi_up"):
            b.btype, b.data0 = ButtonType.DPI_SWITCH, DpiSwitchCode.UP
        elif action in ("dpi-", "dpi_down"):
            b.btype, b.data0 = ButtonType.DPI_SWITCH, DpiSwitchCode.DOWN
        elif action in ("dpiloop", "dpi_cycle", "dpi_loop"):
            b.btype, b.data0 = ButtonType.DPI_SWITCH, DpiSwitchCode.CYCLE
        elif action in ("fire", "burst"):
            rep = int(getattr(args, "repeat", None) or args.val or 3)
            b.btype, b.data0, b.data1, b.data2 = (
                ButtonType.REPEATED,
                ClickCode.LEFT,
                max(1, min(255, rep)),
                30,
            )
        elif action in ("sniper", "snipe", "dpilock"):
            st = int(args.val or 1)
            for other in tbl.buttons:
                if other.slot != hw_slot and other.btype == ButtonType.DPI_LOCK:
                    other.btype, other.data0, other.data1, other.data2 = (
                        ButtonType.DISABLED,
                        0,
                        0,
                        0,
                    )
            b.btype, b.data0, b.data1, b.data2 = (
                ButtonType.DPI_LOCK,
                max(1, min(8, st)),
                0,
                0,
            )
        elif action == "macro":
            macro_idx = int(args.val or 1)
            loop_mode = int(getattr(args, "loop_mode", None) or 1)
            repeat_cnt = int(getattr(args, "repeat", None) or 1)
            b.btype, b.data0, b.data1, b.data2 = (
                ButtonType.MACRO,
                max(1, min(16, macro_idx)),
                loop_mode,
                max(1, min(255, repeat_cnt)),
            )
        elif action in ("disabled", "off", "none"):
            b.btype, b.data0, b.data1, b.data2 = ButtonType.DISABLED, 0, 0, 0
        elif action == "key":
            code = HID_KEY_MAP.get((args.val or "a").lower(), 0x04)
            b.btype, b.data0, b.data1 = ButtonType.KEY, 0, code
        else:
            print(f"Unknown action: {action}")
            return 1
        dev.write_block(serialize_buttons(tbl))
        print(f"Button K{phys_k} ({BUTTON_NAMES[phys_k]}): set to {b.summary()}")
    return 0


def cmd_macro(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        m = OnboardMacro(index=args.id)
        for key in args.keys:
            m.add_key_tap(key, delay_ms=args.delay)
        dev.write_block(serialize_macro(m))
        print(f"Wrote macro #{args.id} with {len(m.events)} events ({', '.join(args.keys)})")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        p = ensure_backup(dev)
        print(f"Backup saved to: {p}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    p = Path(args.dir)
    if not p.is_dir():
        print(f"Backup directory not found: {p}")
        return 1
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        for prof in (1, 2):
            b1 = p / f"p{prof}_b1.bin"
            b2 = p / f"p{prof}_b2.bin"
            if b1.is_file():
                dev.write_block(bytearray(b1.read_bytes()))
            if b2.is_file():
                dev.write_block(bytearray(b2.read_bytes()))
        print(f"Restored configuration from {p}")
    return 0


def cmd_scroll(args: argparse.Namespace) -> int:
    from icarus.scroll import get_scroll_factor, set_scroll_factor
    if getattr(args, "factor", None) is not None:
        set_scroll_factor(args.factor)
        print(f"Scroll factor set to {get_scroll_factor()}")
    else:
        print(f"Current scroll factor: {get_scroll_factor()}")
    return 0


def cmd_help(args: argparse.Namespace) -> int:
    manual = """\
ICARUS - Universal Cross-Distribution Driver & Utility for Gamepower Icarus (258A:0027)

USAGE:
  icarus [COMMAND] [OPTIONS]

COMMANDS:
  (no args)             Launch GUI frontend in app window (or show info if headless)
  gui                   Launch standalone GUI web server & app window
  pull [PATH]           Pull current mouse hardware settings into ~/.config/icarus/config.json
  apply [PATH]          Flash ~/.config/icarus/config.json into mouse hardware memory
  import-bkm <FILE>     Import Windows .BKM backup profile & TEA-decrypted macros
  info                  Display full hardware status, DPI stages, RGB, and button bindings
  profile <1|2>         Switch active onboard hardware profile
  rate <125..1000>      Set USB polling rate in Hz (125, 250, 500, 1000)
  dpi <1..8> <DPI>      Set DPI stage value (400 to 10,000) and optional color
  dpi-stage <1..8>      Switch active DPI stage
  lod <2mm|3mm>         Set PixArt PMW3325 Lift-Off Distance (Low 2mm / High 3mm)
  led <EFFECT>          Set RGB lighting effect (streaming, steady, breathing, neon, off, ...)
  bind <1..9> <ACTION>  Remap physical button K1..K9 (left, right, middle, back, forward, dpi+, ...)
  macro <ID> <KEYS...>  Record and flash macro keystrokes to onboard memory
  backup                Create raw binary flash backup in ~/.local/state/icarus/
  restore <DIR>         Restore raw binary backup folder to hardware flash
  help                  Show this comprehensive manual

CONFIGURATION FILE:
  ~/.config/icarus/config.json  Declarative human & AI-agent editable configuration.
"""
    print(manual)
    return 0
