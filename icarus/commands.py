"""CLI command handlers for Icarus."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

from icarus import bkm
from icarus.backup import ALT_STATE_DIR, STATE_DIR, ensure_backup, restore_backup, verify_backup
from icarus.buttons import (
    BUTTON_NAMES, MULTIMEDIA_ACTIONS, PHYSICAL_TO_SLOT, SPECIAL_HW_ACTIONS,
    ButtonType, ClickCode, DpiSwitchCode, make_multiclick_binding,
    make_multimedia_binding, make_special_binding, parse_buttons, serialize_buttons,
)
from icarus.config import (
    SUPPORTED_LED_MODES, SUPPORTED_RGB_EFFECTS, VALID_DPIS, MouseConfig,
    RgbEffect, is_led_mode_supported, parse_config, serialize_config,
)
from icarus.fileconfig import CONFIG_FILE, apply_to_mouse, pull_from_mouse
from icarus.hidraw import Hidraw, find_vendor_node
from icarus.macros import HID_KEY_MAP, OnboardMacro, serialize_macro
from icarus.protocol import BLOCK_BUTTONS, BLOCK_CONFIG, Device
from icarus.recovery import perform_factory_reset, verify_sensor_motion


def _update_config(fn: Callable[[MouseConfig, int], str | None]) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        act_p = dev.active_profile()
        cfg = parse_config(dev.read_block(act_p, BLOCK_CONFIG))
        msg = fn(cfg, act_p)
        dev.write_block(serialize_config(cfg))
        if msg:
            print(msg)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from icarus.gui import run_gui
    run_gui(host=getattr(args, "host", "127.0.0.1"), port=getattr(args, "port", 8421),
            open_browser=not getattr(args, "no_browser", False))
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        target = Path(args.path) if getattr(args, "path", None) else CONFIG_FILE
        print(f"Pulled mouse hardware configuration into: {pull_from_mouse(Device(h), target)}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        target = Path(args.path) if getattr(args, "path", None) else CONFIG_FILE
        for log in apply_to_mouse(dev, target):
            print(f"  {log}")
        print("Applied configuration file to mouse hardware.")
    return 0


def cmd_import_bkm(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        bkm_path = Path(args.file)
        if not bkm_path.is_file():
            print(f"Error: file not found: {bkm_path}", file=sys.stderr)
            return 1
        prof = bkm.parse_bkm_file(bkm_path)
        print(f"Parsed {bkm_path.name}: {len(prof.macros)} macros decrypted with TEA.")
        for l in bkm.import_bkm_to_mouse(dev, prof, target_profile=args.profile):
            print(f"  {l}")
        print(f"Successfully imported {bkm_path.name} into Profile {args.profile}!")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        act_p = dev.active_profile()
        cfg = parse_config(dev.read_block(act_p, BLOCK_CONFIG))
        lod_s = "High (3mm)" if cfg.lod == 1 else "Low (2mm)"
        print(f"Device: Gamepower Icarus (258a:0027)\nFirmware PSD: {dev.read_psd()}\nActive Profile: {act_p}\n"
              f"\n[Profile {act_p} Settings]\n  Polling Rate : {cfg.polling_rate} Hz\n  LOD          : {lod_s}\n"
              f"  RGB Lighting : {cfg.rgb_effect.name} (Brightness: {cfg.rgb_brightness}/4, Speed: {cfg.rgb_speed}/3)\n"
              f"  Active DPI   : Stage {cfg.active_dpi_stage} ({cfg.dpi_stages[cfg.active_dpi_stage-1].dpi} DPI)\n  DPI Stages   :")
        for idx, s in enumerate(cfg.dpi_stages, 1):
            m, en = ("*" if idx == cfg.active_dpi_stage else " "), ("enabled" if s.enabled else "disabled")
            print(f"   {m} Stage {idx}: {s.dpi:5d} DPI  [RGB({s.color[0]},{s.color[1]},{s.color[2]}):15s] ({en})")
        tbl = parse_buttons(dev.read_block(act_p, BLOCK_BUTTONS))
        print(f"\n[Button Mapping (Profile {act_p})]")
        for k in range(1, 21):
            s = PHYSICAL_TO_SLOT.get(k, k)
            if s - 1 < len(tbl.buttons):
                print(f"  {BUTTON_NAMES.get(k, f'K{k}'):24s} -> {tbl.buttons[s - 1].summary()}")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        dev.set_active_profile(args.id)
        time.sleep(0.05)
        print(f"Active profile set to: {dev.active_profile()}")
    return 0


def cmd_rate(args: argparse.Namespace) -> int:
    return _update_config(lambda c, p: (setattr(c, "polling_rate", args.hz), f"Profile {p} polling rate set to: {args.hz} Hz")[1])


def cmd_dpi(args: argparse.Namespace) -> int:
    if args.val not in VALID_DPIS:
        print(f"Error: {args.val} DPI invalid for PMW3325. Closest: {min(VALID_DPIS, key=lambda d: abs(d - args.val))}", file=sys.stderr)
        return 1
    def _apply(c: MouseConfig, p: int) -> str:
        c.dpi_stages[args.stage - 1].dpi = args.val
        if args.color:
            c.dpi_stages[args.stage - 1].color = tuple(int(x) for x in args.color.split(","))
        return f"Profile {p} stage {args.stage} set to {args.val} DPI"
    return _update_config(_apply)


def cmd_dpi_stage(args: argparse.Namespace) -> int:
    return _update_config(lambda c, p: (setattr(c, "active_dpi_stage", args.stage), f"Profile {p} active DPI stage set to: {args.stage}")[1])


def cmd_lod(args: argparse.Namespace) -> int:
    return _update_config(lambda c, p: (setattr(c, "lod", 1 if args.mode.lower() in ("high", "3mm", "1") else 0),
                                        f"Profile {p} LOD set to: {'High (3mm)' if c.lod == 1 else 'Low (2mm)'}")[1])


def _parse_colors(s: str) -> list[tuple[int, int, int]]:
    return [tuple(int(x) for x in p.split(",") if x.strip()) for p in s.replace(";", " ").replace("|", " ").split() if len(p.split(",")) == 3]


def cmd_led(args: argparse.Namespace) -> int:
    if getattr(args, "list", False):
        print("Supported LED effects (hardware unmasked):")
        for m_id, m_name in sorted(SUPPORTED_LED_MODES.items()):
            print(f"  {m_name:12s} (mode {m_id})")
        return 0
    def _apply(cfg: MouseConfig, p: int) -> str:
        eff_arg = getattr(args, "effect", None)
        if eff_arg:
            eff_upper = eff_arg.upper()
            if eff_upper in RgbEffect._member_names_ and is_led_mode_supported(RgbEffect[eff_upper]):
                cfg.rgb_effect = RgbEffect[eff_upper]
            elif eff_arg.lower() in {v: k for k, v in SUPPORTED_LED_MODES.items()}:
                cfg.rgb_effect = RgbEffect({v: k for k, v in SUPPORTED_LED_MODES.items()}[eff_arg.lower()])
            else:
                print(f"Unsupported effect: {eff_arg}. Supported: {', '.join(sorted(SUPPORTED_LED_MODES.values()))}", file=sys.stderr)
                return ""
        if getattr(args, "brightness", None) is not None:
            cfg.rgb_brightness = max(1, min(4, args.brightness))
        if getattr(args, "speed", None) is not None:
            cfg.rgb_speed = max(1, min(3, args.speed))
        if getattr(args, "direction", None) is not None:
            cfg.rgb_direction = 1 if str(args.direction).lower() in ("1", "backward", "back") else 0
        if getattr(args, "color", None):
            cfg.single_color = tuple(int(x) for x in args.color.split(","))
        if getattr(args, "breathing_colors", None):
            cfg.breathing_colors = _parse_colors(args.breathing_colors)
        return f"Profile {p} RGB effect: {cfg.rgb_effect.name}"
    return _update_config(_apply)


_ACTIONS = {
    "left": (ButtonType.MOUSE_CLICK, ClickCode.LEFT), "right": (ButtonType.MOUSE_CLICK, ClickCode.RIGHT), "middle": (ButtonType.MOUSE_CLICK, ClickCode.MIDDLE),
    "back": (ButtonType.MOUSE_CLICK, ClickCode.BACK), "forward": (ButtonType.MOUSE_CLICK, ClickCode.FORWARD), "dpi+": (ButtonType.DPI_SWITCH, DpiSwitchCode.UP),
    "dpi_up": (ButtonType.DPI_SWITCH, DpiSwitchCode.UP), "dpi-": (ButtonType.DPI_SWITCH, DpiSwitchCode.DOWN), "dpi_down": (ButtonType.DPI_SWITCH, DpiSwitchCode.DOWN),
    "dpiloop": (ButtonType.DPI_SWITCH, DpiSwitchCode.CYCLE), "dpi_cycle": (ButtonType.DPI_SWITCH, DpiSwitchCode.CYCLE), "dpi_loop": (ButtonType.DPI_SWITCH, DpiSwitchCode.CYCLE),
    "disabled": (ButtonType.DISABLED, 0), "off": (ButtonType.DISABLED, 0), "none": (ButtonType.DISABLED, 0),
}


def cmd_bind(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        act_p = dev.active_profile()
        tbl = parse_buttons(dev.read_block(act_p, BLOCK_BUTTONS))
        phys_k = args.slot
        hw_slot = PHYSICAL_TO_SLOT.get(phys_k, phys_k)
        b = tbl.buttons[hw_slot - 1]
        act, nb = args.action.lower(), None
        if act in _ACTIONS:
            b.btype, b.data0, b.data1, b.data2 = _ACTIONS[act][0], _ACTIONS[act][1], 0, 0
        elif act in ("fire", "burst"):
            rep = int(getattr(args, "repeat", None) or args.val or 3)
            b.btype, b.data0, b.data1, b.data2 = ButtonType.REPEATED, ClickCode.LEFT, max(1, min(255, rep)), 30
        elif act in ("sniper", "snipe", "dpilock"):
            st = int(args.val or 1)
            for o in tbl.buttons:
                if o.slot != hw_slot and o.btype == ButtonType.DPI_LOCK:
                    o.btype, o.data0, o.data1, o.data2 = ButtonType.DISABLED, 0, 0, 0
            b.btype, b.data0, b.data1, b.data2 = ButtonType.DPI_LOCK, max(1, min(8, st)), 0, 0
        elif act in ("double", "doubleclick", "double_click"):
            nb = make_multiclick_binding(hw_slot, 2)
        elif act in ("triple", "tripleclick", "triple_click"):
            nb = make_multiclick_binding(hw_slot, 3)
        elif act in MULTIMEDIA_ACTIONS or (act in ("media", "multimedia") and args.val):
            nb = make_multimedia_binding(hw_slot, args.val if act in ("media", "multimedia") else act)
        elif act in SPECIAL_HW_ACTIONS or (act == "special" and args.val):
            nb = make_special_binding(hw_slot, args.val if act == "special" else act)
        elif act == "macro":
            b.btype, b.data0, b.data1, b.data2 = (ButtonType.MACRO, max(1, min(16, int(args.val or 1))),
                                                  int(getattr(args, "loop_mode", None) or 1),
                                                  max(1, min(255, int(getattr(args, "repeat", None) or 1))))
        elif act == "key":
            b.btype, b.data0, b.data1, b.data2 = ButtonType.KEY, 0, HID_KEY_MAP.get((args.val or "a").lower(), 0x04), 0
        else:
            print(f"Unknown action: {act}", file=sys.stderr)
            return 1
        if nb is not None:
            b.btype, b.data0, b.data1, b.data2 = nb.btype, nb.data0, nb.data1, nb.data2
        dev.write_block(serialize_buttons(tbl))
        print(f"Button K{phys_k} ({BUTTON_NAMES.get(phys_k, f'K{phys_k}')}): set to {b.summary()}")
    return 0


def cmd_macro(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        ensure_backup(dev)
        m = OnboardMacro(index=args.id)
        for key in args.keys:
            m.add_key_tap(key, delay_ms=args.delay)
        dev.write_block(serialize_macro(m))
        print(f"Wrote macro #{args.id} with {len(m.events)} events ({', '.join(args.keys)})")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        print(f"Backup saved to: {ensure_backup(Device(h))}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    p = Path(args.dir)
    if not p.is_dir():
        print(f"Backup directory not found: {p}", file=sys.stderr)
        return 1
    with Hidraw(find_vendor_node().path) as h:
        ok = restore_backup(Device(h), p)
        print(f"Restored configuration from {p}" if ok else f"Error: Invalid backup in {p}", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1


def cmd_reset(args: argparse.Namespace) -> int:
    with Hidraw(find_vendor_node().path) as h:
        dev = Device(h)
        print("Performing factory reset & sensor recovery sequence...")
        ok, msg = perform_factory_reset(dev)
        if not ok:
            print(f"Error: {msg}", file=sys.stderr)
            return 1
        print(f"  {msg}")
        if not getattr(args, "skip_motion_check", False):
            print("Verifying optical sensor motion on /dev/hidraw0 (please move mouse)...")
            status = 'ACTIVE (motion detected)' if verify_sensor_motion(timeout_ms=1000) else 'IDLE (no motion detected)'
            print(f"  Sensor status: {status}")
        print("Factory reset complete: restored calibrated defaults and Profile 1.")
    return 0


def cmd_scroll(args: argparse.Namespace) -> int:
    from icarus.scroll import get_scroll_factor, set_scroll_factor
    if getattr(args, "factor", None) is not None:
        set_scroll_factor(args.factor)
    print(f"Current scroll factor: {get_scroll_factor()}")
    return 0


def cmd_help(args: argparse.Namespace) -> int:
    print("""ICARUS - Universal Driver for Gamepower Icarus (258A:0027)
Commands: gui, pull [PATH], apply [PATH], import-bkm <FILE>, info, profile <1|2>,
          rate <125..1000>, dpi <1..8> <DPI>, dpi-stage <1..8>, lod <2mm|3mm>,
          led [EFFECT] [OPTS], bind <1..20> <ACT>, macro <ID> <KEYS...>,
          backup, restore <DIR>, reset, scroll [FACTOR], help""")
    return 0
