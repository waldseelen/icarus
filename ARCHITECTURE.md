# ARCHITECTURE.md — System Blueprint & Data Flow

## 1. Directory Tree & Roles

```
icarusctl/
├── AGENT.md               # Mandatory pointer to CLAUDE.md
├── CLAUDE.md              # Engineering rules and invariants
├── ARCHITECTURE.md        # This document
├── SPEC.md                # Hardware register map and protocol specification
├── MEMORY.md              # Hardware quirks and non-obvious traps
├── PROGRESS.md            # Gate status and session verification log
├── README.md              # User orientation and documentation
├── pyproject.toml         # Packaging metadata
├── bin/
│   └── icarusctl          # In-tree development runner script
├── icarus/
│   ├── __init__.py        # Package exports
│   ├── bkm.py             # TEA decryptor for Windows .BKM macro profiles
│   ├── buttons.py         # 88B button mapping table, presets (multimedia, system, multiclick, special)
│   ├── cli.py             # CLI parser, subcommands & dispatch
│   ├── commands.py        # CLI command execution handlers & backup safety
│   ├── config.py          # 520B config block parser/serializer, DPI math, RGB effects & color sync
│   ├── fileconfig.py      # Declarative JSON schema (~/.config/icarus/config.json)
│   ├── gui.py             # Embedded HTTP server & REST API
│   ├── gui_macros.py      # Macro JSON persistence & flash payload generator
│   ├── hidraw.py          # Sysfs discovery & raw ioctl feature transport
│   ├── macros.py          # Sinowealth macro frame parser & byte encoder
│   ├── protocol.py        # Command framing, retries, profile addressing
│   ├── scroll.py          # Dedicated Hyprland scroll factor IPC & touchpad isolation
│   └── web/
│       ├── index.html     # Desktop GUI single-page canvas & remap modal
│       ├── app.js         # Reactive UI state, live color preview, presets
│       └── style.css      # Dark theme styling, badges, pin layout
├── packaging/
│   ├── udev/
│   │   └── 70-gamepower-icarus.rules  # Uaccess rule for unprivileged /dev/hidraw
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
    ├── data/              # Binary captures from hardware
    ├── test_config.py     # Config block roundtrip, math, and color sync tests
    ├── test_buttons.py    # Button mapping, preset, and multiclick tests
    ├── test_macros.py     # Macro event stream encoder tests
    ├── test_scroll.py     # Scroll speed & touchpad isolation tests
    ├── test_e2e_mock.py   # Mock end-to-end REST API & CLI tests
    └── test_hardware_live.py # Live device validation tests
```

## 2. Layered Architecture

```
[ User Interaction Layer ]
      ├── CLI: icarus.cli -> icarus.commands (rate, dpi, led, bind, macro, backup, pull, apply, scroll)
      └── GUI: icarus.web (HTML5/Canvas) -> icarus.gui (Local REST API Server)
            │
[ File & Window System Integration Layer ]
      ├── icarus.fileconfig: Declarative JSON sync (~/.config/icarus/config.json)
      ├── icarus.scroll: Dedicated Hyprland IPC (device[sinowealth-wired-gaming-mouse])
      └── icarus.bkm: TEA decryptor for Windows OemDrv .BKM profiles
            │
[ Domain Layer: config.py / buttons.py / macros.py / gui_macros.py ]
      ├── Dataclasses (MouseConfig, ButtonTable, ButtonBinding, OnboardMacro)
      ├── RGB mode filtering (LedMask=0x1E8 unmasked modes) & color sync
      ├── Button preset tables (Multimedia 0x22, Shortcuts 0x22, MultiClick 0x33, Special HW 0x50)
      └── Byte packing with commit magics (0x7B config, 0x50 buttons, 0x02 macro write)
            │
[ Protocol Layer: icarus.protocol.Device ]
      ├── Report ID 0x05 command dispatch (PSD, profile select 1/2)
      ├── Report ID 0x04 520-byte block read/write with 0-padding
      └── Exponential backoff retry loop & hardware delay compensation
            │
[ Transport Layer: icarus.hidraw.Hidraw ]
      ├── Locates vendor interface by scanning /sys/class/hidraw/*/device/report_descriptor
      ├── Matches VID 0x258A : PID 0x0027 declaring feature reports 0x04 & 0x05
      └── Dispatches HIDIOCSFEATURE & HIDIOCGFEATURE ioctl calls
            │
[ Linux Kernel Subsystem ]
      ├── /dev/hidrawX (unprivileged access granted by 70-gamepower-icarus.rules)
      └── USB Core (xHCI Host Controller)
            │
[ Gamepower Icarus (Sinowealth 258A:0027) ]
      ├── Interface 0: Standard USB Mouse HID (pointer, clicks, wheel)
      ├── Interface 1: Virtual Keyboard HID (macro playback) + Vendor Config Reports
      └── Onboard Flash MCU & PixArt PMW3325 Sensor
```

## 3. Data Flow

### Read Path
1. `commands.py` / `gui.py` opens `Hidraw` on the vendor node (e.g. `/dev/hidraw2`).
2. `protocol.py` issues Report 0x05 command `0x11` (Profile 1 Config) via `HIDIOCSFEATURE`.
3. Firmware echoes command and stages 141 bytes in internal buffer.
4. `protocol.py` reads Report 0x04 via `HIDIOCGFEATURE`, zero-padding to 520 bytes.
5. `config.py` unpacks DPI array, polling rate byte, RGB effect block, and LOD byte into `MouseConfig`.
6. `protocol.py` issues Report 0x05 command `0x12` (Profile 1 Buttons) and reads 88 bytes into `ButtonTable`.

### Write Path
1. `commands.py` / `gui.py` invokes `ensure_backup()`, saving full dumps to `~/.local/state/icarus/`.
2. Existing config or button block is fetched to preserve untouched calibration bytes.
3. Relevant fields are updated in `MouseConfig` or `ButtonTable`.
4. `config.py` sets Byte 3 to `0x7B` (config magic) or `buttons.py` sets Byte 3 to `0x50` (button magic).
5. `protocol.py` sends Report 0x04 via `HIDIOCSFEATURE`.
6. MCU commits payload to onboard flash memory.

### Scroll Speed Synchronization
1. `scroll.py` queries `hyprctl devices -j` to detect `sinowealth-wired-gaming-mouse`.
2. Applies factor (`0.1..20.0`) dynamically via `hyprctl eval "hl.device({ name = 'sinowealth-wired-gaming-mouse', scroll_factor = <factor> })"`.
3. Persists rule into `~/.config/hypr/input.lua` matching strictly `sinowealth-wired-gaming-mouse`, strictly preserving `input.touchpad` settings.
