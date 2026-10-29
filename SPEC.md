# SPEC.md — Protocol Specification & Hardware Register Map

## 1. Hardware Identifiers & Interfaces

- **Vendor ID (VID):** `0x258A`
- **Product ID (PID):** `0x0027`
- **Microcontroller:** Sinowealth 8051-core HID MCU
- **Optical Sensor:** PixArt PMW3325 (`Sensor = 0x3325`, internal ID `0x0B`)
- **Firmware ID (PSD):** `0x56 0x39 0x30 0x31` (ASCII "V901", checked at `0x412b5c`)

### USB HID Endpoints
- **Input 0 (Interface 0):** Standard boot mouse (Report Descriptor length 70 bytes).
- **Input 1 (Interface 1):** Composite interface declaring:
  - Report ID `0x01`: Standard USB Keyboard
  - Report ID `0x02`: Consumer Controls (Multimedia)
  - Report ID `0x04`: 520-byte Feature Report (Configuration & Macro Data)
  - Report ID `0x05`: 6-byte Feature Report (Command Dispatch & Status)
  - Report ID `0x07`: 7-byte Input Report

## 2. Command Protocol (Report ID 0x05)

Commands are sent via `HIDIOCSFEATURE(6)`:
```
[0x05] [cmd] [arg1] [arg2] [arg3] [arg4]
```

Replies are read via `HIDIOCGFEATURE(6)`:
```
[0x05] [cmd_echo] [ret0] [ret1] [ret2] [ret3]
```

| Command | Args | Description | Reverse Engineering Evidence (VA) |
|---|---|---|---|
| `0x01` | `00 00 00 00` | Read 4-byte Firmware PSD string | `OemDrv.exe @ 0x4134d0` |
| `0x02` | `00 00 00 00` | Read active profile ID (`0x01` or `0x02`) | `OemDrv.exe @ 0x413550` |
| `0x02` | `<p> 00 00 00` | Write active profile ID (`0x01` or `0x02`) | `OemDrv.exe @ 0x4135c0` |
| `0x11` | `00 00 00 00` | Request Profile 1 Config Block | `OemDrv.exe @ 0x41363e` |
| `0x12` | `00 00 00 00` | Request Profile 1 Button Block | `OemDrv.exe @ 0x4137bd` |
| `0x21` | `00 00 00 00` | Request Profile 2 Config Block | `OemDrv.exe @ 0x41364a` |
| `0x22` | `00 00 00 00` | Request Profile 2 Button Block | `OemDrv.exe @ 0x4137c9` |

## 3. Configuration Block (Report ID 0x04, Command 0x11 / 0x21)

Buffer length: 520 bytes.
- **Read Mode:** Byte 3 = `0x00`.
- **Write Mode:** Byte 3 = `0x7B` (Magic trigger required by MCU flash writer, VA `0x413730`).

### Register Map (Offsets inside 520-byte buffer)

| Offset | Length | Name | Description |
|---|---|---|---|
| 0 | 1 B | `report_id` | Must be `0x04` |
| 1 | 1 B | `command_id` | `0x11` (Profile 1) or `0x21` (Profile 2) |
| 2 | 1 B | `reserved` | `0x00` |
| 3 | 1 B | `write_magic` | `0x00` (read), `0x7B` (write commit) |
| 4..8 | 5 B | `hdr_flags` | Header flags (`00 00 06 00 64`) |
| 9 | 1 B | `sensor_type` | `0x0B` for PixArt PMW3325 |
| 10 | 1 B | `polling_rate` | Bits 0..3: `1`=125Hz, `2`=250Hz, `3`=500Hz, `4`=1000Hz |
| 11 | 1 B | `dpi_status` | Bits 0..3: Total stages (8). Bits 4..7: Active stage (0..7) |
| 12 | 1 B | `disabled_mask`| Bitmask of disabled stages (Bit 0 = Stage 1) |
| 13..20 | 8 B | `dpis[8]` | Sensor DPI register values for stages 1..8 |
| 21..28 | 8 B | `dpis_y[8]` | Independent Y DPI values (if enabled) |
| 29..52 | 24 B | `dpi_colors[8]`| 8 × RGB triplets (3 bytes each) for stage indicator LED |
| 53 | 1 B | `rgb_effect` | Effect ID (Filtered via `LedMask=0x1E8`) |
| 54 | 1 B | `rgb_param` | Bits 0..3: Speed (1..3). Bits 4..7: Brightness (1..4) |
| 55 | 1 B | `direction` | RGB wave direction |
| 56 | 1 B | `single_mode` | Static mode brightness / speed |
| 57..59 | 3 B | `single_color` | Static & Reaction mode RGB color |
| 60 | 1 B | `b7_mode` | Breathing mode parameters |
| 61 | 1 B | `b7_count` | Number of active breathing colors (`1` for custom, `7` for spectrum) |
| 62..82 | 21 B | `b7_colors` | 7 × RGB color triplets (`b7_colors[0]` = single breathing color) |
| 129 | 1 B | `lod` | Lift-Off Distance: `0x00` = Low (2mm), `0x01` = High (3mm) |
| 130..519 | 390 B | `padding` | Tail padding (retained from read) |

### Supported RGB Modes (`LedMask = 0x1E8` in `Cfg.ini`)
Reverse engineering `Cfg.ini` reveals `LedMask=0x1E8` (`0b0001_1110_1000`). Only the following 6 modes are implemented in the Icarus MCU firmware:
- `0x00`: **Streaming** (Rainbow fluid wave)
- `0x01`: **Steady** (Single static color from bytes 57..59)
- `0x02`: **Breathing** (Single or 7-color breath, single color stored at bytes 62..64 with byte 61 = 1)
- `0x05`: **Neon** (Continuous color cycling spectrum)
- `0x07`: **Reaction** (Illuminates upon physical click, color stored at bytes 57..59)
- `0x08`: **Off** (LED lighting disabled)

Modes `0x03` (Tail) and `0x04` (Wave) are masked out by `LedMask` and cause erratic color states on this device.

### DPI Encoding Formula
- For DPI $\le$ 5000: $\text{raw} = \frac{\text{DPI}}{100} - 1$
- For DPI $>$ 5000: $\text{raw} = 49 + \frac{\text{DPI} - 5000}{500}$
- Inverse calculation:
  - If $\text{raw} \le 49$: $\text{DPI} = (\text{raw} + 1) \times 100$
  - If $\text{raw} \ge 50$: $\text{DPI} = 5000 + (\text{raw} - 49) \times 500$

## 4. Button Mapping Block (Report ID 0x04, Command 0x12 / 0x22)

Buffer length: 520 bytes (88 bytes active payload).
- **Write Mode:** Byte 3 = `0x50` (Magic trigger, VA `0x4137e0`).
- Entries: 20 slots × 4 bytes starting at offset 8.
  - Byte 0: `type`
  - Byte 1: `data0`
  - Byte 2: `data1`
  - Byte 3: `data2`

### Button Types and Action Opcodes

| Type Code | Category | `data0` | `data1` | `data2` |
|---|---|---|---|---|
| `0x11` | Standard Click | Button Bitmask (`1`=Left, `2`=Right, `4`=Middle, `8`=Back, `16`=Fwd) | `0x00` | `0x00` |
| `0x12` | Wheel Scroll | `0x01` (Up) or `0xFF` (Down) | `0x00` | `0x00` |
| `0x21` | Keyboard Key | Modifier mask (Bit 0=Ctrl, 1=Shift, 2=Alt, 3=Win) | USB HID Keycode | `0x00` |
| `0x22` | Media / Shortcut | Action Category Mask (see table below) | Action Subcode | `0x00` |
| `0x33` | Multi-Click | `0x01` (Left Button trigger) | `0x02` (Double Click), `0x03` (Triple Click) | `0x00` |
| `0x41` | DPI Switch | `0x01` (Cycle), `0x02` (DPI+), `0x03` (DPI-), `0x04` (Lock) | Lock DPI stage | `0x00` |
| `0x50` | Special Hardware | Control Mask (see table below) | `0x00` | `0x00` |
| `0x70` | Onboard Macro | Macro Repeat Mode (`1`=N Times, `2`=Until Key, `3`=Toggle) | Macro Repeat Count | Macro ID |

### Type `0x22`: Multimedia Actions
- Play / Pause: `data0 = 0x01, data1 = 0xcd`
- Stop: `data0 = 0x01, data1 = 0xb7`
- Prev Track: `data0 = 0x01, data1 = 0xb6`
- Next Track: `data0 = 0x01, data1 = 0xb5`
- Volume+: `data0 = 0x01, data1 = 0xe9`
- Volume-: `data0 = 0x01, data1 = 0xea`
- Mute: `data0 = 0x01, data1 = 0xe2`
- Media Player: `data0 = 0x01, data1 = 0x83`

### Type `0x22`: Windows & Browser Shortcuts
- Calculator: `data0 = 0x02, data1 = 0x192`
- My Computer / Explorer: `data0 = 0x02, data1 = 0x194`
- Mail: `data0 = 0x02, data1 = 0x18a`
- Web Home: `data0 = 0x02, data1 = 0x223`
- Web Search: `data0 = 0x02, data1 = 0x221`
- Web Back: `data0 = 0x02, data1 = 0x224`
- Web Forward: `data0 = 0x02, data1 = 0x225`
- Web Stop: `data0 = 0x02, data1 = 0x226`
- Web Refresh: `data0 = 0x02, data1 = 0x227`
- Web Favorites: `data0 = 0x02, data1 = 0x22a`

### Type `0x50`: Special Hardware Controls
- Profile Switch: `data0 = 0x01`
- Polling Rate Switch: `data0 = 0x02`
- Light ON / OFF: `data0 = 0x04`
- Light Mode Switch: `data0 = 0x08`
- Light Color Switch: `data0 = 0x10`
- Light Speed Switch: `data0 = 0x20`
- Light Brightness Switch: `data0 = 0x40`

## 5. Onboard Macro Frame (Report ID 0x04, Command 0x30)

- Byte 0: `0x04`
- Byte 1: `0x30` (`SINOWEALTH_CMD_MACRO`)
- Byte 2: `0x02` (Write flag)
- Byte 8: Macro slot index (1..16)
- Byte 10: Event count $N \le 168$
- Bytes 11..$11 + 3N$: Sequence of 3-byte events:
  - Byte 0: Command (`0x10`=BtnDown, `0x90`=BtnUp, `0x50`=KeyDown, `0xD0`=KeyUp)
  - Byte 1: Delay in milliseconds ($1 \le \text{delay} \le 255$)
  - Byte 2: USB HID usage or button mask

## 6. Scroll Speed Scaling & Touchpad Isolation

Hyprland provides per-device input configuration via IPC and configuration files:
- Target device identifier: `sinowealth-wired-gaming-mouse`
- Factor range: `0.1` to `20.0` (UI preset defaults: `0.5x`, `1.0x`, `3.0x`, `6.0x`, `10.0x`, `15.0x`)
- IPC command: `hyprctl eval "hl.device({ name = 'sinowealth-wired-gaming-mouse', scroll_factor = <factor> })"`
- Persistent file: `~/.config/hypr/input.lua`
- **Isolation Invariant:** Laptop touchpads (e.g., `input.touchpad = { scroll_factor = 0.6 }`) are never modified. Device blocks are strictly targeted by hardware device name.
