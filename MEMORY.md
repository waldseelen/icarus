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

- Bytes 4..8 and 104..128 contain factory sensor calibration constants for the PixArt PMW3325.
- Zeroing out these ranges causes erratic tracking and inaccurate LOD behavior.
- Writers must always base updates on an existing read buffer.

## 6. RGB Mode Masking (`LedMask = 0x1E8`)

- The Sinowealth firmware family defines up to 10 lighting modes, but the Icarus firmware only enables a subset defined by `LedMask = 0x1E8` in `Cfg.ini`.
- Writing unsupported modes like Tail (`0x03`) or Wave (`0x04`) causes the MCU to either fall back to Streaming or freeze the LED strip on arbitrary un-clocked colors.
- Only the 6 unmasked modes (`STREAMING`, `STEADY`, `BREATHING`, `NEON`, `REACTION`, `OFF`) must be exposed in UI and validated on writes.

## 7. Breathing & Reaction Single-Color Synchronization

- In Breathing mode (`0x02`), the MCU reads the single breathing color from `b7_colors[0]` (bytes 62..64) and expects `b7_count` (byte 61) to be set to `1`. If bytes 62..64 are zeroed or byte 61 is set to 7, the mouse unexpectedly cycles spectrum colors.
- In Reaction mode (`0x07`), the MCU reads the click-response color from `single_color` (bytes 57..59).
- Serializers must mirror the user's selected color to both byte positions when writing these modes.

## 8. Hyprland Touchpad Isolation

- Global mouse wheel settings in Wayland compositors can inadvertently accelerate laptop touchpads to uncontrollable speeds.
- In Hyprland, scroll scaling must be applied strictly via per-device configuration targeting `sinowealth-wired-gaming-mouse`.
- Configuration files (`~/.config/hypr/input.lua`) must never touch `input.touchpad = { scroll_factor = ... }`.
