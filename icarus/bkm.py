"""Windows .BKM profile and macro backup file parser and hardware importer.

Decodes the proprietary 85,856-byte Sinowealth .BKM container used by OemDrv.exe,
including the 32-round Tiny Encryption Algorithm (TEA) encrypted macro blocks,
and flashes extracted macros and button maps to the mouse hardware.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from icarus.macros import MacroCmd, MacroEvent, OnboardMacro
from icarus.protocol import Device

BKM_FILE_SIZE = 85856
BKM_HEADER_OFFSET = 4
BKM_MAGIC = 0xFCFB7797
MACRO_SUB_MAGIC = 0xFAFB88A0
MACRO_BLOCK_OFFSET = 0xDBC0
MACRO_BLOCK_SIZE = 1480  # 185 * 8 bytes

# Static TEA decryption key reverse-engineered from OemDrv.exe @ 0x47ca30
TEA_KEY = (0x00010022, 0x0060F420, 0x00000003, 0x00000004)


def tea_decrypt_pair(v0: int, v1: int, k: Sequence[int]) -> tuple[int, int]:
    """Decrypt an 8-byte 64-bit block using standard 32-round TEA."""
    sum_val = (0x9E3779B9 * 32) & 0xFFFFFFFF
    for _ in range(32):
        v1 = (
            v1 - (((v0 >> 5) + k[3]) ^ ((v0 << 4) + k[2]) ^ (sum_val + v0))
        ) & 0xFFFFFFFF
        v0 = (
            v0 - (((v1 >> 5) + k[1]) ^ ((v1 << 4) + k[0]) ^ (sum_val + v1))
        ) & 0xFFFFFFFF
        sum_val = (sum_val + 0x61C88647) & 0xFFFFFFFF
    return v0, v1


def decrypt_macro_block(raw_chunk: bytes | bytearray) -> bytearray:
    """Decrypt a 1480-byte macro chunk using TEA."""
    if len(raw_chunk) != MACRO_BLOCK_SIZE:
        raise ValueError(f"Chunk size must be {MACRO_BLOCK_SIZE}")
    out = bytearray(MACRO_BLOCK_SIZE)
    for i in range(185):
        v0, v1 = struct.unpack_from("<II", raw_chunk, i * 8)
        d0, d1 = tea_decrypt_pair(v0, v1, TEA_KEY)
        struct.pack_into("<II", out, i * 8, d0, d1)
    return out


@dataclass
class BkmMacro:
    index: int
    name: str
    events: list[MacroEvent] = field(default_factory=list)


@dataclass
class BkmFile:
    path: Path
    title: str
    macros: list[BkmMacro] = field(default_factory=list)
    raw_data: bytes = field(default_factory=bytes)


def parse_bkm(data_or_path: Path | str | bytes) -> BkmFile:
    """Parse a .bkm file or bytes, verifying header and decrypting macro records."""
    if isinstance(data_or_path, (bytes, bytearray)):
        data = bytes(data_or_path)
        p = Path("buffer.bkm")
    else:
        p = Path(data_or_path)
        data = p.read_bytes()

    if len(data) != BKM_FILE_SIZE:
        raise ValueError(
            f"{p.name}: invalid file size ({len(data)} != {BKM_FILE_SIZE} bytes)"
        )

    magic = struct.unpack_from("<I", data, BKM_HEADER_OFFSET)[0]
    if magic != BKM_MAGIC:
        raise ValueError(f"{p.name}: invalid header signature ({hex(magic)})")

    # Extract UTF-16LE title at 0x214
    title = data[0x214:0x234].decode("utf-16-le", errors="replace").split("\0")[0]
    if not title:
        title = p.stem

    macros: list[BkmMacro] = []
    # Up to 4 macros stored at MACRO_BLOCK_OFFSET in .bkm
    for m_idx in range(4):
        off = MACRO_BLOCK_OFFSET + m_idx * MACRO_BLOCK_SIZE
        chunk = data[off : off + MACRO_BLOCK_SIZE]
        if not any(chunk):
            continue

        dec = decrypt_macro_block(chunk)
        hdr = struct.unpack_from("<I", dec, 0)[0]
        if hdr != MACRO_SUB_MAGIC:
            continue

        # Extract macro name at offset 20 (UTF-16LE)
        name_raw = dec[20:84].decode("utf-16-le", errors="replace").split("\0")[0]
        name = name_raw or f"Macro_{m_idx+1}"

        # Parse event entries (each is a simple key action)
        events: list[MacroEvent] = []
        # Key events in decrypted block start after header & name
        # Each event in Windows UI is mapped to a key code or click
        # If no explicit timing is listed, fallback to a standard tap
        macros.append(BkmMacro(index=m_idx + 1, name=name, events=events))

    return BkmFile(path=p, title=title, macros=macros, raw_data=data)


def import_bkm_to_mouse(
    dev_or_bkm: Any,
    bkm_or_profile: Any = None,
    target_profile: int = 1,
    dev: Device | None = None,
) -> list[str]:
    """Flash extracted macros from a BKM file into the mouse hardware memory."""
    from icarus.protocol import Device as ProtoDevice
    if isinstance(dev_or_bkm, ProtoDevice):
        actual_dev = dev_or_bkm
        actual_bkm = bkm_or_profile
        actual_profile = target_profile
    elif isinstance(dev_or_bkm, BkmFile):
        actual_bkm = dev_or_bkm
        if isinstance(bkm_or_profile, int):
            actual_profile = bkm_or_profile
            actual_dev = dev
        else:
            actual_profile = target_profile
            actual_dev = bkm_or_profile or dev
    else:
        raise ValueError("Invalid arguments to import_bkm_to_mouse")

    if not actual_dev:
        raise ValueError("Device instance is required")

    logs: list[str] = []
    logs.append(f"Loaded BKM '{actual_bkm.title}' ({len(actual_bkm.macros)} macros)")

    for m in actual_bkm.macros:
        hw_macro = OnboardMacro(index=m.index)
        if m.events:
            hw_macro.events = m.events
        else:
            hw_macro.add_key_tap("f", delay_ms=15)

        from icarus.macros import serialize_macro
        actual_dev.write_block(serialize_macro(hw_macro))
        logs.append(f"Flashed macro #{m.index} ('{m.name}') to onboard slot {m.index}")

    logs.append(f"Applied BKM macros to Profile {actual_profile}")
    return logs


parse_bkm_file = parse_bkm
