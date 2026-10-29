# icarus

**Universal Linux driver, desktop GUI, and configuration utility for the Gamepower Icarus Gaming Mouse (Sinowealth 258a:0027).**

Directly controls DPI stages, polling rate, RGB lighting effects, sensor Lift-Off Distance (LOD), button remapping, scroll wheel speed scaling, and onboard macros via low-level kernel `/dev/hidraw` interfaces without requiring Wine, desktop-specific daemons, or root privileges.

Includes a fast, responsive desktop GUI replicating the original Windows software, single-file declarative JSON configuration (`~/.config/icarus/config.json`), and a reverse-engineered TEA decryptor for importing Windows `.BKM` backup profiles.

---

## Features

- **Distribution Agnostic:** Built 100% with Python 3 standard library. Runs on Arch Linux, Debian, Ubuntu, Fedora, openSUSE, or any standard Linux distribution with **zero external package dependencies** (no npm, no node, no PyQt).
- **Modern Desktop GUI:** Replicates the original Windows 1030×662 canvas with interactive mouse pins (K1..K9), DPI stage sliders, RGB lighting animation preview, categorized remap modal, and .BKM drag-and-drop.
- **Rootless Operation:** Ships with a systemd `uaccess` udev rule granting the active desktop seat user direct access without `sudo`.
- **Scroll Wheel Speed Scaling & Touchpad Isolation:** Scale mouse wheel scroll factor from `0.2x` up to `15.0x` (with presets `0.5x`, `1.0x`, `3.0x`, `6.0x`, `10.0x`, `15.0x`). Automatically isolates laptop touchpads, keeping touchpad scroll factor untouched.
- **Full Button Preset Library:** Support for all original `OemDrv.exe` & `text.xml` button actions:
  - **Multimedia:** Play/Pause, Stop, Next/Prev Track, Volume Up/Down, Mute, Media Player.
  - **Windows & Web Shortcuts:** Explorer, Calculator, Mail, Web Home, Search, Back, Forward, Stop, Refresh, Favorites.
  - **Multi-Click:** Dedicated Double Click and Triple Click triggers (`0x33`).
  - **Hardware Switches:** Profile Switch, Polling Switch, Light ON/OFF, Light Mode, Light Color, Light Speed, Light Brightness.
  - **Gaming Actions:** Fire Burst (3-shot click burst), Sniper Lock (instant low DPI toggle).
- **RGB Mode Filtering & Color Synchronization:** Implements genuine unmasked hardware modes (`LedMask = 0x1E8` in `Cfg.ini`):
  - `STREAMING`: Dynamic multi-color rainbow wave.
  - `STEADY`: Static single color.
  - `BREATHING`: Pulsing light with single-color auto-sync or spectrum breathing.
  - `NEON`: Smooth color cycle spectrum.
  - `REACTION`: Illuminates on click with custom persistent color.
  - `OFF`: Turns off LED lighting completely.
- **Single-File Declarative JSON Config:** All settings stored in `~/.config/icarus/config.json`. Easily edited by humans or AI agents, with `icarus pull` and `icarus apply`.
- **Windows .BKM Import:** Native TEA (Tiny Encryption Algorithm) decryptor parses original Windows backup files (`LOL.bkm`, `OBSIDIAN.bkm`, `GENERAL.bkm`) and flashes macros directly into mouse flash memory.
- **Onboard Flash Memory Writes:** Changes persist inside the mouse microcontroller's flash memory across hardware unplugs and reboots.
- **Sensor Lift-Off Distance (LOD):** Toggle PixArt PMW3325 LOD calibration between Low (2mm) and High (3mm).
- **DPI Management:** Configure up to 8 independent DPI stages (400 to 10,000 DPI) and per-stage LED colors.
- **Polling Rate:** Selectable report rates: 125 Hz, 250 Hz, 500 Hz, or 1000 Hz.
- **Safety Backups:** Automatically dumps existing hardware configurations before writing to flash, with one-command restore capabilities.

---

## Installation

### Method 1: Prebuilt Standalone Binary (Any Linux Distro)

Download or copy `dist/icarus` to your PATH:

```bash
install -m755 dist/icarus ~/.local/bin/icarus
ln -sf icarus ~/.local/bin/icarusctl
```

Install desktop shortcut and icon:
```bash
cp packaging/desktop/icarus.desktop ~/.local/share/applications/
cp icarus/web/assets/icon.png ~/.local/share/pixmaps/icarus.png
```

### Method 2: Debian / Ubuntu (.deb Package)

```bash
sudo dpkg -i dist/icarus_1.0.0_all.deb
```

### Method 3: Arch Linux (PKGBUILD)

```bash
cd packaging/arch && makepkg -si
```

---

## Hardware Permissions (One-Time Setup)

Install the provided udev rule so you never need `sudo`:

```bash
sudo install -m644 packaging/udev/70-gamepower-icarus.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Usage

### 1. Launch GUI Frontend

Simply run `icarus` in terminal or open **Icarus Gaming Mouse** from your application launcher:

```bash
icarus
```
*(If run headlessly or over SSH without a display, `icarus` automatically falls back to showing status output).*

### 2. Declarative JSON Configuration

Pull current mouse hardware settings into a clean JSON file:
```bash
icarus pull
```
Settings are saved to `~/.config/icarus/config.json`. Edit this file in any text editor or with an AI coding agent.

Apply your changes back to the mouse hardware flash:
```bash
icarus apply
```

### 3. Scroll Wheel Speed & Touchpad Isolation

```bash
# Query current scroll speed factor
icarus scroll

# Set mouse wheel scroll factor to 3.0x (touchpad remains untouched)
icarus scroll 3.0

# Set faster scrolling for high-resolution displays
icarus scroll 6.0
```

### 4. Import Windows .BKM Backup Profiles

Directly restore backups exported from the Windows vendor software:
```bash
icarus import-bkm /path/to/LOL.bkm --profile 2
```

### 5. CLI Commands

```bash
# Display full hardware info
icarus info

# Switch active onboard hardware profile (1 or 2)
icarus profile 1

# Change USB polling rate (125, 250, 500, 1000 Hz)
icarus rate 1000

# Set DPI for a stage and optional RGB indicator color
icarus dpi 1 800 --color 0,0,255
icarus dpi 2 1200 --color 255,0,0

# Switch active DPI stage (1..8)
icarus dpi-stage 2

# Set Lift-Off Distance (2mm or 3mm)
icarus lod 2mm

# Configure RGB lighting
icarus led streaming --brightness 4 --speed 3
icarus led steady --color 255,0,0
icarus led breathing --color 0,255,0
icarus led reaction --color 255,0,255

# Remap physical button K1..K9
icarus bind 4 forward
icarus bind 5 back
icarus bind 8 fire
icarus bind 6 play_pause
icarus bind 7 double_click

# Adjust scroll wheel speed
icarus scroll 3.0

# Show comprehensive manual
icarus help
```
