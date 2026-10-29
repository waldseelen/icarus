# CLAUDE.md — Agent & Coding Guidelines for icarusctl

## 0. Non-Negotiable Invariants

1. **Zero External Dependencies:** Runtime must remain 100% Python 3 standard library (`fcntl`, `os`, `struct`, `argparse`, `dataclasses`). Do not add external package dependencies (no `hidapi`, no `pyusb`, no `cffi`).
2. **File Size Limit:** No source file in `icarus/` may exceed 400 lines. Split before hitting the boundary.
3. **Safety Gate Before Flash Writes:** Every command that modifies mouse flash must ensure a full dump of both blocks across all supported profiles is persisted to `~/.local/state/icarusctl/` first.
4. **Preserve Device Calibration:** When writing config or button blocks, always base changes on the active block read from hardware, modifying only task-relevant fields and preserving reserved/calibration bytes.
5. **No Kernel Module:** Hardware is controlled purely in userspace via `/dev/hidraw*` feature reports. The kernel `usbhid` driver handles standard mouse pointer/keyboard clicks concurrently.

## 1. Project Conventions

- **Code Style:** Strict Python 3 type annotations on all functions and methods.
- **Error Handling:** Graceful user-facing error messages on permission denied or disconnected hardware without Python tracebacks in normal CLI execution.
- **Testing:** Unit tests in `tests/` must run via `python3 -m unittest discover tests` with zero setup. Round-trip serialization tests must verify byte-exact preservation against binary fixtures in `tests/data/`.
- **Packaging:** Deliverables must support Arch Linux (PKGBUILD), Debian/Ubuntu (`.deb`), and generic Linux (standalone zipapp executable).

## 2. Reading Order for System Context

1. `ARCHITECTURE.md` — system topology, hardware interface, packet routing
2. `SPEC.md` — low-level HID report schemas, command codes, byte offsets, VA references
3. `MEMORY.md` — hardware quirks, USB STALL behaviors, udev ordering constraints
4. `PROGRESS.md` — test gate status and session log
5. `README.md` — CLI usage instructions and installation
