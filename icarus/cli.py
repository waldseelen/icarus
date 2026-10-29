"""Command line entrypoint and option parser for Icarus."""

from __future__ import annotations

import argparse
import os
import sys

from icarus import commands
from icarus.hidraw import DeviceNotFoundError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Driver & Utility for Gamepower Icarus (258a:0027)",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="Show help")
    subs = parser.add_subparsers(dest="cmd", required=False)

    subs.add_parser("help", help="Show comprehensive manual")
    p_gui = subs.add_parser("gui", help="Launch GUI frontend")
    p_gui.add_argument("--host", default="127.0.0.1", help="HTTP server host")
    p_gui.add_argument("--port", type=int, default=8421, help="HTTP server port")
    p_gui.add_argument("--no-browser", action="store_true", help="Do not launch browser window")

    p_pull = subs.add_parser("pull", help="Pull settings from mouse into JSON config")
    p_pull.add_argument("path", nargs="?", help="Target JSON path (default: ~/.config/icarus/config.json)")

    p_apply = subs.add_parser("apply", help="Apply JSON config to mouse hardware")
    p_apply.add_argument("path", nargs="?", help="Source JSON path (default: ~/.config/icarus/config.json)")

    p_bkm = subs.add_parser("import-bkm", help="Import Windows .BKM backup profile")
    p_bkm.add_argument("file", help="Path to .BKM file")
    p_bkm.add_argument("--profile", type=int, choices=[1, 2], default=1, help="Target profile (1 or 2)")

    subs.add_parser("info", help="Display mouse status and configuration")

    p_prof = subs.add_parser("profile", help="Switch active onboard profile")
    p_prof.add_argument("id", type=int, choices=[1, 2], help="Profile ID (1 or 2)")

    p_rate = subs.add_parser("rate", help="Set USB polling rate")
    p_rate.add_argument("hz", type=int, choices=[125, 250, 500, 1000], help="Rate in Hz")

    p_dpi = subs.add_parser("dpi", help="Configure DPI stage value")
    p_dpi.add_argument("stage", type=int, choices=range(1, 9), help="Stage index (1..8)")
    p_dpi.add_argument("val", type=int, help="DPI value (400..10000)")
    p_dpi.add_argument("--color", type=str, help="RGB color (e.g. 255,0,0)")

    p_st = subs.add_parser("dpi-stage", help="Set active DPI stage")
    p_st.add_argument("stage", type=int, choices=range(1, 9), help="Active stage (1..8)")

    p_lod = subs.add_parser("lod", help="Set sensor Lift-Off Distance")
    p_lod.add_argument("mode", choices=["low", "high", "2mm", "3mm"], help="LOD mode")

    p_led = subs.add_parser("led", help="Configure RGB lighting")
    p_led.add_argument("effect", help="Effect name (streaming, steady, breathing, neon, off, etc.)")
    p_led.add_argument("--brightness", type=int, choices=[1, 2, 3, 4], help="Brightness (1..4)")
    p_led.add_argument("--speed", type=int, choices=[1, 2, 3], help="Animation speed (1..3)")
    p_led.add_argument("--direction", choices=["0", "1", "forward", "backward", "fwd", "back"], help="Wave direction")
    p_led.add_argument("--color", type=str, help="Color for static/steady mode (e.g. 255,0,0)")
    p_led.add_argument("--flicker-colors", type=str, help="2 RGB colors for flicker mode (e.g. '0,255,0;0,0,106')")
    p_led.add_argument("--zone-colors", type=str, help="8 zone RGB colors for colorful steady")
    p_led.add_argument("--breathing-colors", type=str, help="Up to 7 breathing RGB colors")

    p_bind = subs.add_parser("bind", help="Remap button action")
    p_bind.add_argument("slot", type=int, choices=range(1, 10), help="Physical button K1..K9")
    p_bind.add_argument("action", help="Action (left, right, middle, back, forward, dpi+, dpi-, fire, sniper, key, macro)")
    p_bind.add_argument("val", nargs="?", help="Key name, macro ID, sniper stage, or fire repeats")
    p_bind.add_argument("--repeat", type=int, default=None, help="Repeat count for fire key or macro")
    p_bind.add_argument("--loop-mode", type=int, default=None, help="Macro loop mode: 1=Repeat, 2=Hold, 4=Toggle")

    p_mac = subs.add_parser("macro", help="Write an onboard macro sequence")
    p_mac.add_argument("id", type=int, help="Macro ID (1..16)")
    p_mac.add_argument("keys", nargs="+", help="Sequence of keys (e.g. a b c enter)")
    p_mac.add_argument("--delay", type=int, default=15, help="Delay in ms per key event")

    subs.add_parser("backup", help="Backup mouse flash to ~/.local/state/icarus")
    p_rst = subs.add_parser("restore", help="Restore mouse flash from backup folder")
    p_rst.add_argument("dir", help="Path to backup folder")

    p_scr = subs.add_parser("scroll", help="Get or set mouse scroll wheel speed factor")
    p_scr.add_argument("factor", type=float, nargs="?", help="Scroll factor (e.g. 0.5, 1.0, 1.5, 2.0)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.help or args.cmd == "help":
        return commands.cmd_help(args)

    if args.cmd is None:
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            return commands.cmd_gui(args)
        return commands.cmd_info(args)

    cmds = {
        "gui": commands.cmd_gui,
        "pull": commands.cmd_pull,
        "apply": commands.cmd_apply,
        "import-bkm": commands.cmd_import_bkm,
        "info": commands.cmd_info,
        "profile": commands.cmd_profile,
        "rate": commands.cmd_rate,
        "dpi": commands.cmd_dpi,
        "dpi-stage": commands.cmd_dpi_stage,
        "lod": commands.cmd_lod,
        "led": commands.cmd_led,
        "bind": commands.cmd_bind,
        "macro": commands.cmd_macro,
        "backup": commands.cmd_backup,
        "restore": commands.cmd_restore,
        "scroll": commands.cmd_scroll,
    }

    try:
        handler = cmds.get(args.cmd)
        if not handler:
            return commands.cmd_help(args)
        return handler(args)
    except DeviceNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except PermissionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
