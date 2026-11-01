# MEMORY.md — Hardware Quirks & Non-Obvious Traps

## 1. Profile 3 USB STALL Trap

- The mouse firmware accepts profile ID `3` when executing `CMD_PROFILE (0x02)`.
- However, the MCU flash only allocates memory for profiles `1` and `2`.
- Any subsequent attempt to query block `1` (`0x31`) or block `2` (`0x32`) triggers an immediate USB Control Pipe STALL. Under Linux, this manifests as `[Errno 32] Broken pipe` on `ioctl(HIDIOCGFEATURE)`.
- **Rule:** Supported hardware profile IDs must strictly be constrained to `(1, 2)`.

## 2. Udev Rule Ordering Constraint

- Systemd-logind applies `uaccess` ACLs through `/usr/lib/udev/rules.d/73-seat-late.rules`.
- Any rule that tags a node with `TAG+="uaccess"` must sort **lexicographically before** `73-seat-late.rules`.
- A file named `99-gamepower-icarus.rules` is processed too late: `logind` ignores the tag, and the device node remains restricted to `root:root 0600`.
- **Rule:** The udev rule file is named `70-gamepower-icarus.rules`.

## 3. Flash Write Triggers (Magic Bytes)

- The MCU will silently discard configuration writes that do not include the exact byte-count offset in Byte 3:
  - Configuration blocks require Byte 3 = `0x7B` (123).
  - Button blocks require Byte 3 = `0x50` (80).
- Writing `0x00` in Byte 3 performs a no-op read mirror without flashing memory.

## 4. Short Report Read Padding

- When reading Report `0x04`, the mouse firmware sends only the populated bytes over the USB wire (141 bytes for config, 86 bytes for buttons) rather than a full 520-byte packet.
- When writing back, the host **must** transmit a full 520-byte feature report.
- The transport layer must always zero-pad inbound reports to 520 bytes before handing them to parsers.

## 5. Non-Destructive Calibration Preservation

- Bytes 4..8, 104..128, and 130..131 contain factory sensor calibration constants for the PixArt PMW3325.
- Zeroing or modifying these ranges (such as overwriting `buf[130]` or writing experimental mode data to `buf[116..125]`) corrupts sensor engine registers, halting relative motion events while button clicks remain functional.
- Writers must always base updates on an existing read buffer and copy `104..128` (except 129) and `130..131` byte-exact.

## 6. RGB Mode Masking (`LedMask = 0x1E8`)

- The Sinowealth firmware family defines up to 10 lighting modes (0..9 in `text.xml` / `OemDrv.exe @ 0x4367bf`), but the Icarus firmware only enables a subset defined by `LedMask = 0x1E8` in `Cfg.ini`.
- The UI loop tests `LedMask & (1 << i)` where non-zero bits skip/mask the mode. Bits 3, 5, 6, 7, 8 are masked out.
- Only the 5 unmasked modes (`STREAMING` = 0, `STEADY` = 1, `BREATHING` = 2, `NEON` = 4, `OFF` = 9) are supported by hardware and exposed in the CLI/GUI.

## 7. Breathing Single-Color Synchronization

- In Breathing mode (`0x02`), the MCU reads the single breathing color from `b7_colors[0]` (bytes 62..64) and expects `b7_count` (byte 61) to be set to `1`. If bytes 62..64 are zeroed or byte 61 is set to 7, the mouse unexpectedly cycles spectrum colors.
- Serializers must mirror the user's selected breathing color to `b7_colors[0]` when writing single-color breathing mode.

## 8. Hyprland Touchpad Isolation

- Global mouse wheel settings in Wayland compositors can inadvertently accelerate laptop touchpads to uncontrollable speeds.
- In Hyprland, scroll scaling must be applied strictly via per-device configuration targeting `sinowealth-wired-gaming-mouse`.
- Configuration files (`~/.config/hypr/input.lua`) must never touch `input.touchpad = { scroll_factor = ... }`.
