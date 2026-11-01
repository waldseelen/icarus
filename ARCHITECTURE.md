# ARCHITECTURE.md — System Blueprint & Data Flow

## 1. Directory Tree & Component Responsibilities

```
icarusctl/
├── AGENT.md               # Mandatory pointer to CLAUDE.md
├── CLAUDE.md              # Engineering rules and non-negotiable invariants
├── ARCHITECTURE.md        # This document (system blueprint & hardware topology)
├── SPEC.md                # Low-level HID report schemas & register codex
├── MEMORY.md              # Hardware quirks and non-obvious traps
├── PROGRESS.md            # Test gate status and session verification log
├── README.md              # CLI orientation and usage guide
├── pyproject.toml         # Packaging metadata
├── bin/
│   └── icarusctl          # In-tree development CLI launcher
├── icarus/
│   ├── __init__.py        # Package namespace exports
│   ├── backup.py          # Mandatory pre-write state dumps to ~/.local/state/icarusctl/
│   ├── recovery.py        # Calibrated factory reset & optical sensor wake sequence
│   ├── hidraw.py          # Sysfs discovery & ioctl feature transport
│   ├── protocol.py        # Report 0x05/0x04 framing, retries, and profile addressing
│   ├── config.py          # 520B config block parsing/serialization, DPI math, RGB effects
│   ├── buttons.py         # 88B button mapping table, slots K1..K20, multimedia & presets
│   ├── macros.py          # Sinowealth macro frame parser & byte encoder
│   ├── bkm.py             # TEA decryptor for Windows OemDrv .BKM profiles
│   ├── fileconfig.py      # Declarative JSON schema (~/.config/icarus/config.json)
│   ├── scroll.py          # Dedicated Hyprland scroll factor IPC & touchpad isolation
│   ├── cli.py             # CLI parser, subcommands & argument validation
│   ├── commands.py        # CLI command dispatchers & business logic
│   ├── gui_macros.py      # Macro JSON persistence & flash payload generator
│   ├── gui.py             # Embedded HTTP server & REST API
│   └── web/
│       ├── index.html     # Single-page desktop GUI application
│       ├── app.js         # Reactive UI state and event handlers
│       └── style.css      # Dark theme styling, badges, pin layout
├── packaging/
│   ├── udev/
│   │   └── 70-gamepower-icarus.rules  # Uaccess udev rule for unprivileged /dev/hidraw
│   ├── desktop/
│   │   └── icarus.desktop             # Freedesktop application entry
│   ├── arch/
│   │   └── PKGBUILD                   # Arch Linux package build recipe
│   └── debian/
│       ├── control                    # Debian package metadata
│       └── rules                      # Debian build automation
├── scripts/
│   ├── build-dist.sh      # Build zipapp executable and distribution tarball
│   └── build-deb.py       # Pure-python Debian .deb archive builder
└── tests/
    ├── data/              # Binary factory calibration captures (p1_b1, p1_b2, p2_b1, p2_b2)
    ├── test_config.py     # Config block roundtrip, DPI math, and color sync tests
    ├── test_buttons.py    # Button mapping, preset, and multiclick tests
    ├── test_macros.py     # Macro event stream encoder tests
    ├── test_scroll.py     # Scroll speed & touchpad isolation tests
    ├── test_e2e_mock.py   # Mock end-to-end REST API & CLI tests
    └── test_hardware_live.py # Live device validation tests
```

---

## 2. Hardware Topology & Device Separation

The Gamepower Icarus (USB VID:PID `258A:0027`) exposes two distinct USB HID interfaces on the host bus:

```
+-----------------------------------------------------------------------------------------+
|                               Linux USB Host Subsystem                                  |
|                                                                                         |
|      /dev/hidraw0 (Interface 0)                       /dev/hidraw1 (Interface 1)        |
|  • Sysfs: .../7-1:1.0/.../hidraw0                 • Sysfs: .../7-1:1.1/.../hidraw1      |
|  • Endpoint: 0x81 IN (1000 Hz, 8B)                • Endpoint: 0x82 IN (1000 Hz, 8B)     |
|  • Function: Relative Motion (dx, dy)             • Function: Macro Keyboard Playback   |
|              Physical Button Clicks (Left, etc.)              Feature Report 0x04 (520B)|
|              Wheel Scroll & Tilt                              Feature Report 0x05 (6B)  |
+-----------------------------------------------------------------------------------------+
                                             |
                         USB 2.0 Full-Speed (12 Mbps, VID:PID = 258A:0027)
                                             |
+--------------------------------------------v--------------------------------------------+
|                              Sinowealth 8051-Core MCU                                   |
|                             (SH68F83 / BY8832 Firmware)                                 |
|                                                                                         |
|  [GPIO Matrix]                                 [Internal Flash Memory]                  |
|  • Physical microswitches (K1..K9)              • Profile 1 Config Block 1 (Cmd 0x11)   |
|  • Rotary optical encoder (Wheel)              • Profile 1 Button Block 2 (Cmd 0x12)   |
|                                                • Profile 2 Config Block 1 (Cmd 0x21)   |
|                                                • Profile 2 Button Block 2 (Cmd 0x22)   |
|                                                • Macro Storage Blocks (Cmd 0x30)       |
+-----------------------------------------------------------------------------------------+
                                             |
                              Internal 4-Wire SPI Bus + MOTION_INT
                              (NCS, SCLK, SDIO/MOSI, MISO, MOTION_INT)
                                             |
+--------------------------------------------v--------------------------------------------+
|                          PixArt PMW3325DB-TWV1 Optical Engine                           |
|  • Native Resolution: 200 - 5000 DPI (Interpolated up to 10000 DPI)                     |
|  • Internal State Machine: Run -> Rest1 -> Rest2 -> Rest3 (Pulsing 3-4 Hz LED)          |
|  • Registers: Shutter Threshold, LiftCutoff_Tune0 (0x6A), Run Calibration               |
+-----------------------------------------------------------------------------------------+
```

### Device Separation Invariants

1. **Interface 0 (`/dev/hidraw0`):**
   - Purely an input stream.
   - Polled by the Linux kernel `usbhid` driver to generate standard pointer displacement events (`EV_REL`) and button clicks (`EV_KEY`).
   - Used in `icarusctl` exclusively for non-blocking read-only verification of sensor motion vectors.
2. **Interface 1 (`/dev/hidraw1`):**
   - The vendor control interface.
   - All configuration, profile switching, lighting controls, button mapping, and macro flashing MUST be addressed exclusively to this node via `HIDIOCSFEATURE` and `HIDIOCGFEATURE`.
3. **Touchpad Isolation (`/dev/hidraw2`):**
   - `/dev/hidraw2` on the host machine belongs to the internal Synaptics touchpad (`SYNA32E4:00 06CB:CEE7`, `hid-multitouch`).
   - Device discovery in `icarus.hidraw` strictly filters by vendor ID `0x258A`, product ID `0x0027`, and the presence of Report IDs `0x04` and `0x05` in the report descriptor. `/dev/hidraw2` is never opened or modified.

---

## 3. Optical Sensor State Machine & Rest2/Rest3 Sleep Trap

The PixArt PMW3325 optical tracking engine features an internal multi-stage power-saving state machine:

```
[ Active Movement ]
        │
        ▼
   ┌─────────┐       Idle > 1 sec       ┌──────────┐
   │   Run   │ ───────────────────────> │  Rest 1  │
   │ (~6.7mA)│                          │ (~1.6mA) │
   └─────────┘                          └──────────┘
        ▲                                     │
        │ Movement Detected                   │ Idle > 10 sec
        │                                     ▼
        │   Surface Correlation Succeeded   ┌──────────┐
        └────────────────────────────────── │  Rest 2  │ (72 µA, 3-4 Hz LED pulse)
        │                                   └──────────┘
        │                                     │ Idle > 10 min
        │                                     ▼
        │                                   ┌──────────┐
        └────────────────────────────────── │  Rest 3  │ (56 µA, 3-4 Hz LED pulse)
                                            └──────────┘
                 Surface Correlation Failed (Sleep Trap)
                 ───────────────────────────────────────> Sensor stays in Rest2/Rest3
```

### Normal Operating Flow

1. **Run Mode:** Continuous high-frequency optical frame capture (up to 5000 fps). The sensor compares successive surface images to calculate $(\Delta X, \Delta Y)$ displacement. Upon detecting movement, it asserts `MOTION_INT` to the Sinowealth MCU, which reads displacement over SPI and dispatches 7-byte motion packets on EP 0x81.
2. **Rest1 / Rest2 / Rest3 Modes:** When stationary, the sensor steps down power consumption. In Rest2 and Rest3, the LED pulses at a low duty cycle (3-4 Hz). Each pulse takes a single surface exposure.
3. **Wakeup Transition:** If the exposure shows pixel delta exceeding the background noise threshold, the sensor asserts `MOTION_INT` and immediately transitions back to Run mode.

### The Rest2/Rest3 Sleep Trap Mechanism

The root cause of optical sensor tracking loss is flash calibration corruption:
1. When unmasked LED modes (modes 6, 7, 8) or malformed configuration blocks are written to the mouse flash, the data overwrites bytes 104..132 in Config Block 1.
2. These bytes hold the PMW3325 SPI register initialization data:
   - Shutter threshold registers (offsets 120-121)
   - SPI register `0x6A` (`LiftCutoff_Tune0`, offset 122)
   - Lift-Off Detection mode (offset 123)
   - Optical run calibration constants (offsets 130-131)
3. During boot or profile switching, the Sinowealth MCU transmits these corrupted bytes across the SPI bus into the PMW3325 registers.
4. When the sensor pulses at 3-4 Hz in Rest2/Rest3, its correlation engine compares the surface reflection against corrupted threshold values:
   - The engine fails to acquire a valid focal contrast match.
   - It assumes the mouse is lifted off the mousepad (LOD trip) or out of focus.
   - It aborts the transition to Run mode and resets its internal wake timer.
5. Consequently, `MOTION_INT` is never asserted. The Sinowealth MCU reports `dx = 0, dy = 0` on every interrupt interval on EP 0x81.
6. Meanwhile, physical button clicks and the scroll wheel continue functioning normally because the MCU GPIO scanning matrix operates independently of the optical tracking engine.

---

## 4. Sensor Recovery Sequence

Sensor recovery is achieved by restoring valid optical calibration constants to MCU flash and forcing an SPI re-initialization:

```
[ Step 1: Mandatory Backup ]
  Dump Profile 1 & 2 blocks (520B each) to ~/.local/state/icarusctl/backup_<timestamp>/
            │
            ▼
[ Step 2: Write Profile 2 Factory Blocks ]
  Write p2_b1.bin (Config, Magic 0x7B) & p2_b2.bin (Buttons, Magic 0x50) via Report 0x04
            │
            ▼
[ Step 3: Write Profile 1 Factory Blocks ]
  Write p1_b1.bin (Config, Magic 0x7B) & p1_b2.bin (Buttons, Magic 0x50) via Report 0x04
            │
            ▼
[ Step 4: Hardware Settle Delay ]
  Pause 20 ms (Sleep 0x14 matching OemDrv.exe @ 0x00417319)
            │
            ▼
[ Step 5: Active Profile Commit ]
  Dispatch Report 0x05 CMD_PROFILE (0x02) with argument 0x01 (SetActiveProfile 1)
            │
            ▼
[ Step 6: MCU Firmware Action ]
  MCU commits flash, resets optical engine state, and transmits valid calibration
  constants (shutter 0x0000, reg 0x6A, run_cal 0x01 0x00) to PMW3325 over SPI
            │
            ▼
[ Step 7: Optical Sensor Wakeup ]
  On the next 3-4 Hz pulse, surface correlation succeeds.
  PMW3325 enters Run mode, asserts MOTION_INT, and streams relative dx/dy on /dev/hidraw0
```

---

## 5. System Invariants & Architectural Constraints

1. **Zero External Dependencies:**
   - Runtime code is strictly 100% Python 3 standard library (`fcntl`, `os`, `struct`, `argparse`, `dataclasses`, `time`, `pathlib`).
   - External dependencies (such as `hidapi`, `pyusb`, `cffi`, or `requests`) are prohibited.
2. **Modular File Size Limit ($\le 400$ Lines):**
   - No Python module in `icarusctl/icarus/` may exceed 400 lines (`wc -l`).
   - Architectural responsibilities are cleanly segregated into dedicated modules:
     * `backup.py`: State dumping and backup integrity verification
     * `recovery.py`: Factory reset and optical sensor wake sequence
     * `commands.py`: CLI dispatcher (streamlined to remain well under the 400-line ceiling)
3. **Mandatory Pre-Write State Backup:**
   - Every code path that modifies mouse flash memory must execute a complete state dump of both blocks across Profile 1 and Profile 2 to `~/.local/state/icarusctl/backup_<timestamp>/` prior to sending write packets.
4. **Preservation of Factory Calibration Constants:**
   - Configuration updates must always read the active block first, modify only user-requested fields, and preserve offsets 104..135 byte-exact.
5. **Userspace Driver Architecture:**
   - Operates purely in userspace using `ioctl` feature reports via `/dev/hidraw*`.
   - No custom kernel module is required or allowed.

---

## 6. Layered Architecture & Data Flow

```
+-----------------------------------------------------------------------------------------+
|                                User Interaction Layer                                   |
|   • CLI (icarus.cli -> icarus.commands): rate, dpi, led, bind, macro, backup, reset   |
|   • GUI (icarus.web -> icarus.gui): Canvas UI communicating via embedded REST server    |
+-----------------------------------------------------------------------------------------+
                                             │
+--------------------------------------------v--------------------------------------------+
|                          System & Configuration Sync Layer                              |
|   • icarus.fileconfig: Declarative JSON persistence (~/.config/icarus/config.json)      |
|   • icarus.scroll: Hyprland Wayland IPC for device-specific scroll scaling              |
|   • icarus.bkm: TEA decryptor for legacy Windows OemDrv macro profiles                 |
+-----------------------------------------------------------------------------------------+
                                             │
+--------------------------------------------v--------------------------------------------+
|                                      Domain Layer                                       |
|   • icarus.config: MouseConfig dataclass, DPI piecewise formula, LedMask=0x1E8 check   |
|   • icarus.buttons: ButtonTable, slots K1..K20, multimedia & special hardware actions   |
|   • icarus.macros / icarus.gui_macros: OnboardMacro event stream serializer             |
|   • icarus.backup: Pre-write snapshot validation and directory management               |
|   • icarus.recovery: Calibrated reset blocks & PMW3325 wake orchestration              |
+-----------------------------------------------------------------------------------------+
                                             │
+--------------------------------------------v--------------------------------------------+
|                                     Protocol Layer                                      |
|   • icarus.protocol.Device: Report 0x05 command dispatch, Report 0x04 520B framing,    |
|     magic injection (0x7B config, 0x50 buttons, 0x02 macro), 3x retry loop with 200ms   |
+-----------------------------------------------------------------------------------------+
                                             │
+--------------------------------------------v--------------------------------------------+
|                                    Transport Layer                                      |
|   • icarus.hidraw.Hidraw: Sysfs tree scanning, VID/PID matching, uaccess permission     |
|     handling, HIDIOCSFEATURE & HIDIOCGFEATURE ioctl calls                               |
+-----------------------------------------------------------------------------------------+
```

### Read Data Flow

1. High-level caller requests mouse state (`icarusctl status` or `GET /api/status`).
2. `hidraw.py` identifies the vendor device node (`/dev/hidraw1`).
3. `protocol.py` issues Report 0x05 opcode `0x11` (Profile 1 Config) via `HIDIOCSFEATURE`.
4. Firmware stages the 520-byte configuration block in its transmission FIFO.
5. `protocol.py` reads Report 0x04 via `HIDIOCGFEATURE`.
6. `config.py` deserializes the 520-byte payload into `MouseConfig` (polling rate, DPI table, active stage, unmasked RGB effect, brightness, speed, LOD distance).
7. `protocol.py` issues Report 0x05 opcode `0x12` (Profile 1 Buttons) and reads 520 bytes.
8. `buttons.py` deserializes offsets 8..87 into `ButtonTable` containing slots K1 through K20.

### Write Data Flow

1. User requests a configuration change (e.g. `icarusctl dpi 1600` or `icarusctl led steady --color ff0000`).
2. The safety gate (`backup.py:ensure_backup`) is invoked, creating a full timestamped snapshot of Profile 1 and Profile 2 blocks in `~/.local/state/icarusctl/`.
3. The current block is read from hardware to obtain active calibration bytes (offsets 104..135).
4. `config.py` or `buttons.py` applies the user-specified mutations while retaining all reserved and calibration bytes intact.
5. `protocol.py` sets byte 3 to `0x7B` for Config Blocks or `0x50` for Button Blocks, pads the buffer to 520 bytes, and writes the block via `HIDIOCSFEATURE`.
6. The host pauses 20 ms and dispatches Report 0x05 `SetActiveProfile` (`0x02`) to trigger the MCU flash commit and SPI reload.

### Scroll Speed Synchronization Flow

1. `scroll.py` scans connected Hyprland devices using `hyprctl devices -j`.
2. Locates the device matching `name = "sinowealth-wired-gaming-mouse"`.
3. Dispatches runtime scaling via `hyprctl eval "hl.device({ name = 'sinowealth-wired-gaming-mouse', scroll_factor = <factor> })"`.
4. Writes the persistent configuration snippet to `~/.config/hypr/input.lua`.
5. Verifies that the internal laptop touchpad configuration block (`input.touchpad`) remains untouched.
