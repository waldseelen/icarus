# SPEC.md — Protocol Specification & Hardware Register Map

## 1. Hardware Identifiers & USB Topology

- **Vendor ID (VID):** `0x258A`
- **Product ID (PID):** `0x0027`
- **Microcontroller:** Sinowealth 8051-core HID MCU (SH68F83 / BY8832 firmware)
- **Optical Sensor:** PixArt PMW3325DB-TWV1 (Sensor ID `0x3325`, internal ID mask `0x0B`)
- **Firmware ID (PSD):** `0x56 0x39 0x30 0x31` (ASCII "V901", checked at `0x412b5c`)

### USB HID Endpoints & Interfaces

The device presents two independent USB interfaces under a composite configuration:

- **Interface 0 (Input 0 / `/dev/hidraw0`):**
  - Endpoint: `0x81` (EP 1 IN, Interrupt, 8 bytes, `bInterval = 1` ms, 1000 Hz polling)
  - Report Descriptor length: 71 bytes (declares implicit Report ID 0)
  - Report format: 7-byte motion packet:
    `[buttons (1B), dx_low (1B), dx_high (1B), dy_low (1B), dy_high (1B), wheel (1B), hwheel (1B)]`
    * `buttons`: Bitmask (Bit 0 = Left, Bit 1 = Right, Bit 2 = Middle, Bit 3 = Back, Bit 4 = Forward)
    * `dx`, `dy`: 16-bit signed little-endian integers (two's complement relative motion)
    * `wheel`, `hwheel`: 8-bit signed integers (vertical scroll and horizontal tilt)

- **Interface 1 (Input 1 / `/dev/hidraw1`):**
  - Endpoint: `0x82` (EP 2 IN, Interrupt, 8 bytes, virtual keyboard / macro event playback)
  - Report Descriptor length: 213 bytes, declaring:
    * Report ID `0x01`: Standard USB Keyboard input report (8 bytes)
    * Report ID `0x02`: Consumer controls / multimedia input report (3 bytes)
    * Report ID `0x04`: 520-byte Feature Report (Flash memory blocks for configuration, buttons, macros)
    * Report ID `0x05`: 6-byte Feature Report (Command dispatch & status register)
    * Report ID `0x07`: 7-byte vendor input report

- **Touchpad Isolation Invariant:**
  - `/dev/hidraw2` is the internal laptop Synaptics touchpad (`SYNA32E4:00 06CB:CEE7`, `hid-multitouch`).
  - All host control commands and flash transfers must strictly target `/dev/hidraw1` matching `0003:0000258A:00000027`.

---

## 2. Command Protocol (Report ID 0x05)

Command exchange takes place over a 6-byte bidirectional Feature Report on Interface 1 (`/dev/hidraw1`).

### Frame Formats

Commands are dispatched via `HIDIOCSFEATURE(6)`:
```
[0x05] [cmd] [arg0] [arg1] [arg2] [arg3]
```

Replies are retrieved via `HIDIOCGFEATURE(6)`:
```
[0x05] [cmd_echo] [ret0] [ret1] [ret2] [ret3]
```

### Calling Conventions & Retry Logic

- **`SendCmd` (`OemDrv.exe @ 0x00413180`):**
  1. Writes 6-byte buffer `[0x05, cmd, arg0, arg1, arg2, arg3]` using `SetFeature`.
  2. Retry policy: Up to 3 attempts with a 200 ms delay (`Sleep(200)`) between consecutive failures.
- **`GetCmd` (`OemDrv.exe @ 0x00413250`):**
  1. Reads 6-byte buffer `[0x05, 0x00, 0x00, 0x00, 0x00, 0x00]` using `GetFeature`.
  2. Returns 5 bytes payload: `cmd_echo` followed by return arguments `ret0..ret3`.
- **Profile Commit Delay:**
  After issuing `SetActiveProfile` (`cmd = 0x02`), the host must pause for at least 20 ms before issuing subsequent feature report requests (`OemDrv.exe @ 0x00417319`: `push 0x14; call Sleep`).

### Complete Opcode Table

| Opcode (`cmd`) | Arguments (`arg0..arg3`) | Disassembly VA | Function / Description | Return Payload |
|---|---|---|---|---|
| `0x01` | `00 00 00 00` | `0x004134d0` | **GetPSD**: Query 4-byte firmware version string | `0x56 0x39 0x30 0x31` (ASCII `"V901"`) |
| `0x02` | `00 00 00 00` | `0x00413550` | **GetActiveProfile**: Query hardware active profile | `ret0` = Active profile index (`1` or `2`) |
| `0x02` | `<p> 00 00 00` | `0x004135c0` | **SetActiveProfile**: Switch active profile (`<p>` = `1` or `2`) | Success acknowledgment |
| `0x11` | `00 00 00 00` | `0x0041363e` | **Arm Read P1 Config**: Stage Profile 1 Config Block for Report 0x04 | MCU prepares 520B buffer |
| `0x12` | `00 00 00 00` | `0x004137bd` | **Arm Read P1 Buttons**: Stage Profile 1 Button Block for Report 0x04 | MCU prepares 520B buffer |
| `0x21` | `00 00 00 00` | `0x0041364a` | **Arm Read P2 Config**: Stage Profile 2 Config Block for Report 0x04 | MCU prepares 520B buffer |
| `0x22` | `00 00 00 00` | `0x004137c9` | **Arm Read P2 Buttons**: Stage Profile 2 Button Block for Report 0x04 | MCU prepares 520B buffer |
| `0x31` | `00 00 00 00` | `0x00413656` | **Arm Read P3 Config**: Defined in firmware; triggers USB STALL on 2-profile Icarus hardware | USB STALL (`EPIPE`) |
| `0x32` | `00 00 00 00` | `0x004137d5` | **Arm Read P3 Buttons**: Defined in firmware; triggers USB STALL on 2-profile Icarus hardware | USB STALL (`EPIPE`) |

---

## 3. Configuration Block (Report ID 0x04, Opcodes 0x11 / 0x21)

Buffer length: 520 bytes.
- **Read Mode:** Preceded by Report 0x05 opcode `0x11` (P1) or `0x21` (P2). Byte 3 is returned as `0x00`.
- **Write Mode:** Byte 3 must be set to `0x7B` (`OemDrv.exe @ 0x00413730`). Without `0x7B`, the MCU discards the flash write.

### Exhaustive Byte-Level Offset Layout (Offsets 0..135)

| Offset | Length | Field Name | Description & Value Encoding | Factory P1 | Factory P2 |
|---|---|---|---|---|---|
| `0` | 1 B | `report_id` | Must be `0x04` | `0x04` | `0x04` |
| `1` | 1 B | `block_opcode` | `0x11` (Profile 1) or `0x21` (Profile 2) | `0x11` | `0x21` |
| `2` | 1 B | `reserved` | Reserved zero byte | `0x00` | `0x00` |
| `3` | 1 B | `write_magic` | Flash write commit magic: `0x7B` for write; `0x00` on read | `0x00` (read) | `0x00` (read) |
| `4..7` | 4 B | `hdr_magic` | Block header identifier sequence: `0x00, 0x00, 0x06, 0x00` | `00 00 06 00` | `00 00 06 00` |
| `8` | 1 B | `hdr_flag` | Profile header flag: `0x64` (100 decimal) for P1, `0x00` for P2 | `0x64` | `0x00` |
| `9` | 1 B | `sensor_id` | Optical sensor family mask: `(buf[9] & 0x3F) == 0x0B` (PMW3325) | `0x0B` | `0x0B` |
| `10` | 1 B | `polling_rate` | Bits 0..3: `1`=125Hz, `2`=250Hz, `3`=500Hz, `4`=1000Hz. Bit 7: Independent XY DPI (`0x80` = enabled) | `0x04` (1000Hz) | `0x02` (250Hz) |
| `11` | 1 B | `dpi_status` | Bits 0..3: Total configured stages (1..8, factory=8). Bits 4..7: Active stage index (1-indexed in driver, 1..8) | `0x38` (Active 3, Total 8) | `0x28` (Active 2, Total 8) |
| `12` | 1 B | `disabled_mask`| Bitmask of disabled DPI stages (Bit 0 = Stage 1, Bit 7 = Stage 8; `0`=enabled, `1`=disabled) | `0x00` | `0x00` |
| `13..20` | 8 B | `dpis[8]` | DPI stage raw register values for stages 1..8 (see DPI formula below) | `04 07 09 0a 0b 0e 27 31` | `04 07 09 0e 13 1d 27 31` |
| `21..28` | 8 B | `dpis_y[8]` | Independent Y-axis DPI stage values (active when `buf[10] & 0x80` is set) | `00 00 00 00 00 00 00 00` | `00 00 00 00 00 00 00 00` |
| `29..52` | 24 B | `dpi_colors[8]`| 8 × RGB color triplets (3 bytes per stage: Red, Green, Blue) for DPI indicator LED | 8 RGB triplets | 8 RGB triplets |
| `53` | 1 B | `rgb_effect` | LED effect mode ID (must be unmasked by `LedMask = 0x1E8`): `0`=Streaming, `1`=Steady, `2`=Breathing, `4`=Neon, `9`=Off (`Cfg.ini` installer default is `0x00` Streaming; `p1_b1.bin` fixture has `0x02` Breathing, `p2_b1.bin` has `0x01` Steady) | `0x02` (Breathing) | `0x01` (Steady) |
| `54` | 1 B | `rgb_param` | Bits 0..3: Speed (`1`=Slow, `2`=Medium, `3`=Fast). Bits 4..7: Brightness (`1`=25%, `2`=50%, `3`=75%, `4`=100%) | `0x32` (Bright 3, Speed 2) | `0x02` (Speed 2, Bright 0) |
| `55` | 1 B | `rgb_direction`| Wave direction: `0x00` = Clockwise / Forward, `0x01` = Counter-clockwise / Reverse | `0x00` | `0x00` |
| `56` | 1 B | `steady_param` | Steady mode brightness / speed parameter | `0x10` | `0x40` |
| `57..59` | 3 B | `steady_color` | RGB triplet (R, G, B) for Steady mode | `0x00, 0xC0, 0xC0` (Cyan) | `0xFF, 0x00, 0xFF` (Magenta) |
| `60` | 1 B | `breathing_param`| Breathing effect speed and brightness parameter | `0x42` | `0x02` |
| `61` | 1 B | `breathing_count`| Number of breathing colors: `1` = single custom color, `7` = 7-color spectrum cycle | `0x06` | `0x07` |
| `62..82` | 21 B | `breathing_colors[7]`| 7 × RGB triplets for breathing stages (`breathing_colors[0]` holds the custom single color) | 7 RGB triplets | 7 RGB triplets |
| `83..103` | 21 B | `reserved_lighting`| Secondary lighting buffer padding (must be preserved byte-exact from read) | Factory bytes | Factory bytes |
| `104` | 1 B | `pmw3325_shutter_l`| PMW3325 Shutter register lower byte | `0x00` | `0xFA` |
| `105..119`| 15 B | `pmw3325_cal_pre`| Optical sensor calibration constants (`00 ff ff 00 00 ff 00 00 ff 00 00 02 00 ff 00`) | Calibration sequence | Calibration sequence |
| `120..121`| 2 B | `pmw3325_shutter_thresh`| 16-bit little-endian shutter threshold: P1 = `0x0000`, P2 = `0x03FA` (1018 decimal) | `0x00, 0x00` | `0xFA, 0x03` |
| `122` | 1 B | `pmw3325_reg_6a`| PixArt PMW3325 SPI register 0x6A (`LiftCutoff_Tune0` = `0x6A`) | `0x6A` | `0x6A` |
| `123` | 1 B | `pmw3325_lod_mode`| Lift-Off Detection Mode: P1 = `0x00`, P2 = `0x02` | `0x00` | `0x02` |
| `124..128`| 5 B | `pmw3325_cal_post`| Sensor calibration sequence: `0x02, 0x00, 0x00, 0x00, 0x00` | `02 00 00 00 00` | `02 00 00 00 00` |
| `129` | 1 B | `pmw3325_lod_distance`| Lift-Off Distance: `0x00` = Low (2mm), `0x01` = High (3mm) | `0x01` (High 3mm) | `0x00` (Low 2mm) |
| `130..131`| 2 B | `pmw3325_run_cal`| Factory optical calibration constants: P1 = `0x01, 0x00`, P2 = `0x44, 0xF0` | `0x01, 0x00` | `0x44, 0xF0` |
| `132..135`| 4 B | `sensor_ident_tail`| Sensor identification tail: `0x01, 0x04, 0x06, 0x0B` (`0x0B` = PMW3325) | `01 04 06 0B` | `01 04 06 0B` |
| `136..519`| 384 B | `padding` | Tail padding (384 bytes of `0x00`) | All `0x00` | All `0x00` |

### DPI Encoding Formulas

The PMW3325 sensor uses a piecewise linear scale for resolution registers:

- **Encoding (DPI to Register Value):**
  - For $\text{DPI} \le 5000$: $\text{raw} = \frac{\text{DPI}}{100} - 1$
  - For $\text{DPI} > 5000$: $\text{raw} = 49 + \frac{\text{DPI} - 5000}{500}$
  - Examples:
    * 500 DPI $\rightarrow (500 / 100) - 1 = 4$ (`0x04`)
    * 800 DPI $\rightarrow (800 / 100) - 1 = 7$ (`0x07`)
    * 1000 DPI $\rightarrow (1000 / 100) - 1 = 9$ (`0x09`)
    * 1500 DPI $\rightarrow (1500 / 100) - 1 = 14$ (`0x0E`)
    * 4000 DPI $\rightarrow (4000 / 100) - 1 = 39$ (`0x27`)
    * 5000 DPI $\rightarrow (5000 / 100) - 1 = 49$ (`0x31`)
    * 10000 DPI $\rightarrow 49 + (10000 - 5000) / 500 = 59$ (`0x3B`)

- **Decoding (Register Value to DPI):**
  - For $\text{raw} \le 49$: $\text{DPI} = (\text{raw} + 1) \times 100$
  - For $\text{raw} \ge 50$: $\text{DPI} = 5000 + (\text{raw} - 49) \times 500$

---

## 4. Button Mapping Block (Report ID 0x04, Opcodes 0x12 / 0x22)

Buffer length: 520 bytes (88 bytes active payload, 432 bytes tail zero padding).
- **Read Mode:** Preceded by Report 0x05 opcode `0x12` (P1) or `0x22` (P2). Byte 3 returns `0x00`.
- **Write Mode:** Byte 3 must be set to `0x50` (`OemDrv.exe @ 0x004137e0`). Without `0x50`, the MCU discards the button table write.

### Slot Allocation Map (Offsets 8..87)

The table stores 20 slots of 4 bytes each (`[type, data0, data1, data2]`):

| Slot | Buffer Offsets | Physical Button / Default Function | Factory Binding (P1) | P1 Hex | Factory Binding (P2) | P2 Hex |
|---|---|---|---|---|---|---|
| **K1** | `8..11` | Left Click | Mouse Click (Left) | `11 01 00 00` | Mouse Click (Left) | `11 01 00 00` |
| **K2** | `12..15` | Right Click | Mouse Click (Right) | `11 02 00 00` | Mouse Click (Right) | `11 02 00 00` |
| **K3** | `16..19` | Middle Click / Wheel Click | Mouse Click (Middle) | `11 04 00 00` | Mouse Click (Middle) | `11 04 00 00` |
| **K4** | `20..23` | Forward Button (Side) | Onboard Macro Slot 1 | `70 01 01 01` | Recoil Macro Mode 0x61 | `61 13 0f 2f` |
| **K5** | `24..27` | Back Button (Side) | Mouse Click (Back) | `11 08 00 00` | Recoil Macro Mode 0x62 | `62 01 0f 10` |
| **K6** | `28..31` | DPI Switch Top Button | Media Control (Play/Pause) | `22 08 00 00` | DPI Step Up (`DPI+`) | `41 01 00 00` |
| **K7** | `32..35` | Side Extra Button 1 | Onboard Macro Slot 2 | `70 02 01 01` | DPI Step Down (`DPI-`) | `41 02 00 00` |
| **K8** | `36..39` | Side Extra Button 2 | Onboard Macro Slot 3 | `70 03 01 01` | Keyboard Key '=' | `21 00 2e 00` |
| **K9** | `40..43` | Side Extra Button 3 | Onboard Macro Slot 4 | `70 04 01 01` | Keyboard Key 'F' | `21 00 09 00` |
| **K10**| `44..47` | Extended Slot 10 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K11**| `48..51` | Extended Slot 11 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K12**| `52..55` | Extended Slot 12 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K13**| `56..59` | Extended Slot 13 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K14**| `60..63` | Extended Slot 14 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K15**| `64..67` | Extended Slot 15 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K16**| `68..71` | Extended Slot 16 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K17**| `72..75` | Extended Slot 17 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K18**| `76..79` | Extended Slot 18 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K19**| `80..83` | Extended Slot 19 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **K20**| `84..87` | Extended Slot 20 | Hardware Switch (Profile) | `50 01 00 00` | Disabled | `00 00 00 00` |
| **Pad**| `88..519`| Reserved Flash Padding | 432 bytes of zeros | All `0x00` | 432 bytes of zeros | All `0x00` |

### Action Types & Opcodes Codex (0x11..0x70)

#### `0x11`: Standard Mouse Click
- `data0`: Button bitmask:
  * `0x01` = Left Button
  * `0x02` = Right Button
  * `0x04` = Middle Button
  * `0x08` = Back Button (Button 4)
  * `0x10` = Forward Button (Button 5)
- `data1`: `0x00`
- `data2`: `0x00`

#### `0x12`: Wheel Scroll
- `data0`: Direction: `0x01` = Scroll Up, `0xFF` = Scroll Down
- `data1`: `0x00`
- `data2`: `0x00`

#### `0x13`: Tilt Scroll
- `data0`: Direction: `0xFF` = Tilt Left, `0x01` = Tilt Right
- `data1`: `0x00`
- `data2`: `0x00`

#### `0x21`: Keyboard Key
- `data0`: Modifier bitmask:
  * Bit 0 (`0x01`): Left/Right Ctrl
  * Bit 1 (`0x02`): Left/Right Shift
  * Bit 2 (`0x04`): Left/Right Alt
  * Bit 3 (`0x08`): GUI / Windows key
- `data1`: Standard USB HID Keycode (Usage Page 0x07, e.g. `0x04` = 'A', `0x2C` = Space)
- `data2`: `0x00`

#### `0x22`: Multimedia & Consumer Shortcuts
The Sinowealth firmware encodes multimedia and consumer controls as a 3-byte bitfield `[data0, data1, data2]` (e.g. factory default for Slot K6 is `22 08 00 00` for Play / Pause):
- `data0` bitmask (Media Player Controls):
  * `0x01`: Next Track
  * `0x02`: Previous Track
  * `0x04`: Stop
  * `0x08`: Play / Pause
  * `0x10`: Mute
  * `0x40`: Volume Up
  * `0x80`: Volume Down
- `data1` bitmask (Application Shortcuts):
  * `0x01`: Media Player
  * `0x02`: File Explorer ("My Computer")
  * `0x10`: Email Client
  * `0x20`: Calculator
- `data2` bitmask (Web Browser Controls):
  * `0x01`: Web Search
  * `0x02`: Web Home
  * `0x04`: Web Back
  * `0x08`: Web Forward
  * `0x10`: Web Stop
  * `0x20`: Web Refresh
  * `0x40`: Web Favorites

#### `0x31` / `0x33`: Multi-Click (Burst Fire)
- `data0`: Trigger button (`0x01` = Left Button)
- `data1`: Inter-click delay in milliseconds (`0x32` = 50 ms default)
- `data2`: Burst count (`0x02` = Double Click, `0x03` = Triple Click)

#### `0x41`: DPI Control
- `data0`: Subfunction:
  * `0x00`: Cycle through active DPI stages
  * `0x01`: DPI Step Up (`DPI+`)
  * `0x02`: DPI Step Down (`DPI-`)
- `data1`: `0x00`
- `data2`: `0x00`

#### `0x42`: DPI Sniper Lock
- `data0`: Target DPI stage index (1..8) to maintain while physical button is held down
- `data1`: `0x00`
- `data2`: `0x00`

#### `0x50`: Hardware Control Switches (MCU Internal)
- `data0`: Target hardware function code (sequential codes):
  * `0x01`: Profile Switch (toggles between Profile 1 and Profile 2)
  * `0x02`: Polling Rate Switch (cycles 125Hz, 250Hz, 500Hz, 1000Hz)
  * `0x04`: Lighting ON / OFF toggle
  * `0x06`: Lighting Mode Switch (cycles lighting effects)
  * `0x07`: Lighting Color Switch (cycles effect colors)
  * `0x08`: Lighting Speed Switch (cycles effect speeds)
  * `0x09`: Lighting Brightness Switch (cycles brightness levels)
- `data1`: `0x00`
- `data2`: `0x00`

#### `0x60..0x62`: Recoil Macro / Gun Compensation
- `data0`: Weapon mode / pattern ID
- `data1`: Vertical recoil compensation step
- `data2`: Repeat rate / cycle timing

#### `0x70`: Onboard Macro Trigger
- `data0`: Target onboard macro slot ID (1..16)
- `data1`: Repeat execution mode:
  * `0x01`: Execute macro $N$ times
  * `0x02`: Loop macro continuously while the physical button is held down
  * `0x04`: Loop until any key is pressed
- `data2`: Repeat count $N$ (for mode `0x01`)

---

## 5. Onboard Macro Block (Report ID 0x04, Opcode 0x30)

Buffer length: 520 bytes.
Macro sequences are written to flash using Report ID `0x04` with opcode `0x30`.

### Header Framing

- `buf[0]`: Report ID = `0x04`
- `buf[1]`: Opcode = `0x30` (`SINOWEALTH_CMD_MACRO`)
- `buf[2]`: Write flag = `0x02` for flash writes; `0x00` on read
- `buf[3..7]`: Reserved zero padding (`0x00`)
- `buf[8]`: Macro Slot ID (1..16)
- `buf[9..10]`: 16-bit event count $N$ in big-endian order (`buf[9] = (N >> 8) & 0xFF`, `buf[10] = N & 0xFF`), where $1 \le N \le 168$

### Event Stream Structure (Offsets 11..$11 + 3N$)

Events are packed as contiguous 3-byte tuples `[cmd_delay_hi, delay_lo, key_code]` with 12-bit delay encoding ($1..4095$ ms) across Byte 0 and Byte 1:

| Byte | Field | Description |
|---|---|---|
| `0` | `cmd_delay_hi` | High nibble holds event command opcode (`cmd & 0xF0`): `0x10` = Mouse Down, `0x90` = Mouse Up, `0x20` = Wheel, `0x30` = Move X, `0x40` = Move Y, `0x50` = Key Down, `0xD0` = Key Up. Low nibble holds upper 4 bits of the 12-bit delay: `(delay_ms >> 8) & 0x0F`. Wire byte: `(cmd & 0xF0) \| ((delay_ms >> 8) & 0x0F)`. |
| `1` | `delay_lo` | Lower 8 bits of the 12-bit timing delay in milliseconds: `delay_ms & 0xFF` ($1 \le \text{delay\_ms} \le 4095$). |
| `2` | `key_code` | Input code: For keyboard events (`0x50`/`0xD0`), standard USB HID usage code (Usage Page 0x07). For mouse button events (`0x10`/`0x90`), button bitmask (`0x01`=Left, `0x02`=Right, `0x04`=Middle). For wheel (`0x20`) or pointer movement (`0x30`/`0x40`), signed delta byte. |

Unused bytes between offset $11 + 3N$ and 519 are filled with `0x00`.

---

## 6. PixArt PMW3325 SPI Registers & Sensor Calibration

The Sinowealth MCU interfaces with the PixArt PMW3325 optical sensor over an internal 4-wire SPI bus (NCS, SCLK, SDIO/MOSI, MISO) plus an active-low `MOTION_INT` interrupt line.

During MCU initialization or active profile switching, the MCU copies the sensor calibration registers from Config Block 1 (offsets 104..132) into the PMW3325 internal SPI registers.

### PMW3325 SPI Register Map in Flash

```
Offset in Block 1    Length    Target SPI Register / Name    Description & Behavior
---------------------------------------------------------------------------------------------------------
104                  1 B       pmw3325_shutter_l             Lower 8 bits of shutter time calibration
105..119             15 B      pmw3325_cal_pre               Optical engine correlation threshold matrix
120..121             2 B       pmw3325_shutter_thresh        16-bit little-endian shutter upper threshold:
                                                             P1 = 0x0000; P2 = 0x03FA (1018 decimal)
122                  1 B       pmw3325_reg_6a                PixArt SPI register 0x6A (LiftCutoff_Tune0 = 0x6A)
123                  1 B       pmw3325_lod_mode              Lift-Off Detection Mode: P1 = 0x00, P2 = 0x02
124..128             5 B       pmw3325_cal_post              Surface focus constants: 0x02, 0x00, 0x00, 0x00, 0x00
129                  1 B       pmw3325_lod_distance          Lift-Off Distance: 0x00 = Low (2mm), 0x01 = High (3mm)
130..131             2 B       pmw3325_run_cal               Factory run calibration constants:
                                                             P1 = 0x01, 0x00; P2 = 0x44, 0xF0
132..135             4 B       sensor_ident_tail             Optical engine tail: 0x01, 0x04, 0x06, 0x0B (PMW3325)
```

### Factory Calibration Invariant

- Profile 1 calibration values:
  `p1_b1[104:136] = 00 00 ff ff 00 00 ff 00 00 ff 00 00 02 00 ff 00 00 00 6a 00 02 00 00 00 00 01 01 00 01 04 06 0b`
- Profile 2 calibration values:
  `p2_b1[104:136] = fa 00 ff ff 00 00 ff 00 00 ff 00 00 02 00 ff 00 fa 03 6a 02 02 00 00 00 00 00 44 f0 01 04 06 0b`

These bytes are factory-calibrated for optical focal distance and surface tracking. They must never be zeroed, randomized, or overwritten during user configuration updates.

---

## 7. LED Subsystem & Register Overwrite Analysis

### Supported LED Modes & Parameter Encoding

The Sinowealth firmware and PMW3325 optical engine support 5 verified LED modes defined by the hardware mask:

| Mode ID | Name | Description | Key Configuration Parameters |
|---|---|---|---|
| `0x00` | **Streaming** | Fluid multi-color RGB rainbow wave | `rgb_param` (Speed 1..3, Brightness 1..4), `rgb_direction` |
| `0x01` | **Steady** | Static solid single color | `steady_color` (bytes 57..59 RGB), `steady_param` (brightness) |
| `0x02` | **Breathing** | Pulsating illumination | `breathing_param` (speed/bright), `breathing_count` (1 for custom single color at bytes 62..64; 7 for spectrum cycle) |
| `0x04` | **Neon** | Continuous smooth spectrum cycling | `rgb_param` (Speed 1..3, Brightness 1..4) |
| `0x09` | **Off** | Lighting completely disabled | LED driver disabled in MCU |

### Parameter Byte Packing

- **Byte 54 (`rgb_param`):**
  - Bits 0..3: Speed (`0x01` = Slow, `0x02` = Medium, `0x03` = Fast)
  - Bits 4..7: Brightness (`0x01` = 25%, `0x02` = 50%, `0x03` = 75%, `0x04` = 100%)
  - Example: Speed 2, Brightness 3 $\rightarrow (3 \ll 4) \mid 2 = \text{0x32}$
- **Byte 55 (`rgb_direction`):**
  - `0x00`: Clockwise / Forward wave
  - `0x01`: Counter-clockwise / Reverse wave

### `LedMask = 0x1E8` Filtering & Corruption Mechanism

`Cfg.ini` defines:
```ini
LedMask=0x1E8
```

In binary, `0x1E8` is `0b0001_1110_1000`:
- Bit 3 (`1 << 3 = 8`): Mode 3 (Colorful Tail)
- Bit 5 (`1 << 5 = 32`): Mode 5 (Colorful Steady)
- Bit 6 (`1 << 6 = 64`): Mode 6 (Flicker)
- Bit 7 (`1 << 7 = 128`): Mode 7 (Stars Twinkle)
- Bit 8 (`1 << 8 = 256`): Mode 8 (Wave)
- Total sum: $8 + 32 + 64 + 128 + 256 = 488 = \text{0x1E8}$.

In `OemDrv.exe @ 0x004367bf`, the UI loops through mode indices $0 \le i \le 9$:
```c
if (LedMask & (1 << i)) {
    // Skip adding mode i to the UI dropdown
    continue;
}
```

Testing `LedMask & (1 << i)` masks out modes 3, 5, 6, 7, and 8.

### Exact Overwrite Mechanism on PMW3325 Registers

When unmasked Sinowealth driver variants write configuration buffers for modes 3, 5, 6, 7, or 8, the lighting data spills past offset 59 into higher buffer regions:
- **Mode 3 (Colorful Tail):** Writes colors to offsets 60..82.
- **Mode 4 (Neon):** Writes speed to offset 83.
- **Mode 5 (Colorful Steady):** Writes color to offset 84.
- **Mode 6 (Flicker):** Writes color arrays to offsets 85..109. Offset 104 (`pmw3325_shutter_l`) and calibration offsets 105..109 are directly overwritten with RGB color values.
- **Mode 7 (Stars Twinkle):** Writes parameters to offsets 116..122. Offset 120..121 (`pmw3325_shutter_thresh`) and offset 122 (`pmw3325_reg_6a`) are overwritten with color and twinkle speed values.
- **Mode 8 (Wave):** Writes wave parameters to offset 123. Offset 123 (`pmw3325_lod_mode`) is overwritten.

When the MCU receives a block where modes 6, 7, or 8 have been written, it writes these corrupted values to the PMW3325 SPI registers. The PMW3325 optical tracking engine is unable to focus or correlate surface reflections, causing the sensor to trap itself in the `Rest2/Rest3` sleep state.

---

## 8. Scroll Speed Scaling & Touchpad Isolation

Hyprland Wayland compositor provides per-device input configuration via IPC and configuration scripts:
- **Device Identifier:** `sinowealth-wired-gaming-mouse`
- **Factor Range:** `0.1` to `20.0` (Presets: `0.5x`, `1.0x`, `3.0x`, `6.0x`, `10.0x`, `15.0x`)
- **IPC Command:** `hyprctl eval "hl.device({ name = 'sinowealth-wired-gaming-mouse', scroll_factor = <factor> })"`
- **Persistent Configuration File:** `~/.config/hypr/input.lua`
- **Touchpad Isolation Invariant:**
  The internal laptop touchpad configuration block (`input.touchpad = { scroll_factor = ... }`) is strictly untouched. All modifications filter exclusively on `sinowealth-wired-gaming-mouse`.
