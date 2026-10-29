"""Configuration block (report 0x04, command 0x11/0x21) parser and serializer.

Translates the mouse onboard flash configuration block (DPI stages, polling rate,
RGB lighting effects, lift-off distance) into structured Python dataclasses and
serializes back to the exact wire format expected by the Sinowealth firmware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Sequence

CONFIG_BLOCK_SIZE = 140
CONFIG_WRITE_MAGIC = 0x7B
REPORT_DATA = 0x04

# Polling rate mapping: raw byte -> Hz
RAW_TO_RATE = {1: 125, 2: 250, 3: 500, 4: 1000}
RATE_TO_RAW = {125: 1, 250: 2, 500: 3, 1000: 4}


class RgbEffect(IntEnum):
    OFF = 0
    STREAMING = 1  # Colorful Streaming
    STEADY = 2  # Steady single color
    STATIC = 2  # Backward compatibility alias
    BREATHING = 3  # Breathing cycle
    BREATHING7 = 3  # Backward compatibility alias
    COLORFUL_TAIL = 4  # Colorful Tail
    TAIL = 4  # Backward compatibility alias
    NEON = 5  # Neon spectral color cycle
    COLORFUL_STEADY = 6  # 8-zone Colorful Steady
    CONSTANT = 6  # Backward compatibility alias
    FLICKER = 7  # 2-color flicker
    RAVE = 7  # Backward compatibility alias
    STARS_TWINKLE = 8  # Stars twinkle
    RANDOM = 8  # Backward compatibility alias
    WAVE = 9  # Wave
    REACTION = 10  # Reaction burst on click
    BREATHING1 = 10  # Backward compatibility alias


# Genuine hardware-supported modes unmasked by LedMask=0x1E8 in Cfg.ini
SUPPORTED_RGB_EFFECTS: tuple[RgbEffect, ...] = (
    RgbEffect.OFF,
    RgbEffect.STREAMING,
    RgbEffect.STEADY,
    RgbEffect.BREATHING,
    RgbEffect.NEON,
    RgbEffect.REACTION,
)


# PixArt PMW3325 57 discrete hardware steps: 400..5000 (step 100), 5500..10000 (step 500)
VALID_DPIS: tuple[int, ...] = tuple(
    list(range(400, 5001, 100)) + list(range(5500, 10001, 500))
)


def raw_to_dpi(raw: int) -> int:
    """Convert sensor raw DPI byte (0..59) to integer DPI value."""
    if raw < 0 or raw > 59:
        raise ValueError(f"Sensor raw DPI byte {raw} out of supported range (0..59)")
    if raw <= 49:
        return (raw + 1) * 100
    return 5000 + (raw - 49) * 500


def dpi_to_raw(dpi: int) -> int:
    """Convert integer DPI value (400..10000) to sensor raw byte."""
    if dpi not in VALID_DPIS:
        raise ValueError(f"DPI {dpi} is not a valid hardware step (must be in VALID_DPIS)")
    if dpi <= 5000:
        return (dpi // 100) - 1
    return 49 + (dpi - 5000) // 500


def snap_dpi(dpi: int) -> int:
    """Snap arbitrary DPI to nearest valid PMW3325 hardware step."""
    return min(VALID_DPIS, key=lambda d: abs(d - dpi))


# Supported channel orders for hardware LED pins
CHANNEL_ORDERS: dict[str, tuple[int, int, int]] = {
    "RGB": (0, 1, 2),
    "BGR": (2, 1, 0),
    "GRB": (1, 0, 2),
    "BRG": (2, 0, 1),
    "RBG": (0, 2, 1),
    "GBR": (1, 2, 0),
}


def permute_color_to_hw(rgb: tuple[int, int, int], order: str = "RGB") -> tuple[int, int, int]:
    idx = CHANNEL_ORDERS.get(order.upper(), (0, 1, 2))
    return (rgb[idx[0]], rgb[idx[1]], rgb[idx[2]])


def permute_color_from_hw(hw: tuple[int, int, int], order: str = "RGB") -> tuple[int, int, int]:
    idx = CHANNEL_ORDERS.get(order.upper(), (0, 1, 2))
    inv = [0, 1, 2]
    for i, p in enumerate(idx):
        inv[p] = i
    return (hw[inv[0]], hw[inv[1]], hw[inv[2]])


@dataclass
class DpiStage:
    dpi: int
    color: tuple[int, int, int]
    enabled: bool = True


@dataclass
class MouseConfig:
    profile: int
    polling_rate: int  # 125, 250, 500, 1000 Hz
    active_dpi_stage: int  # 1..8
    dpi_stages: list[DpiStage] = field(default_factory=list)
    rgb_effect: RgbEffect = RgbEffect.STREAMING
    rgb_brightness: int = 4  # 1..4
    rgb_speed: int = 2  # 1..3
    rgb_direction: int = 0  # 0 = Forward, 1 = Backward (Byte 55)
    single_color: tuple[int, int, int] = (255, 0, 0)
    breathing_colors: list[tuple[int, int, int]] = field(default_factory=list)
    zone_colors: list[tuple[int, int, int]] = field(default_factory=list)
    flicker_colors: list[tuple[int, int, int]] = field(default_factory=list)
    lod: int = 0  # 0 = 2mm (Low), 1 = 3mm (High)
    channel_order: str = "RGB"
    raw_buffer: bytearray = field(default_factory=lambda: bytearray(520))

    @property
    def breathing7_colors(self) -> list[tuple[int, int, int]]:
        return self.breathing_colors

    @breathing7_colors.setter
    def breathing7_colors(self, val: list[tuple[int, int, int]]) -> None:
        self.breathing_colors = val


def parse_config(data: bytes | bytearray, channel_order: str = "RGB") -> MouseConfig:
    """Parse a 520-byte report-0x04 config block."""
    if len(data) < CONFIG_BLOCK_SIZE or data[0] != REPORT_DATA:
        raise ValueError(f"Invalid config report header (len={len(data)})")

    cmd = data[1]
    profile = (cmd >> 4) & 0x0F
    if profile not in (1, 2):
        raise ValueError(f"Unsupported profile id in config: {profile}")

    raw_rate = data[10] & 0x0F
    polling_rate = RAW_TO_RATE.get(raw_rate, 1000)

    stage_info = data[11]
    raw_active = (stage_info >> 4) & 0x0F
    disabled_mask = data[12]

    dpi_stages: list[DpiStage] = []
    for i in range(8):
        raw_dpi = data[13 + i]
        dpi_val = raw_to_dpi(raw_dpi)
        c_off = 29 + i * 3
        raw_c = (data[c_off], data[c_off + 1], data[c_off + 2])
        color = permute_color_from_hw(raw_c, channel_order)
        enabled = not bool(disabled_mask & (1 << i))
        dpi_stages.append(DpiStage(dpi=dpi_val, color=color, enabled=enabled))

    effect = (
        RgbEffect(data[53])
        if data[53] in RgbEffect._value2member_map_
        else RgbEffect.STREAMING
    )

    # Read dedicated mode register slices
    direction = 1 if data[55] else 0
    raw_single = (data[57], data[58], data[59])
    single_color = permute_color_from_hw(raw_single, channel_order)

    b_count = min(7, max(1, data[61]))
    breathing_colors = [
        permute_color_from_hw((data[62 + i * 3], data[62 + i * 3 + 1], data[62 + i * 3 + 2]), channel_order)
        for i in range(b_count)
    ]

    zone_colors = [
        permute_color_from_hw((data[86 + i * 3], data[86 + i * 3 + 1], data[86 + i * 3 + 2]), channel_order)
        for i in range(8)
    ]

    flicker_colors = [
        permute_color_from_hw((data[117 + i * 3], data[117 + i * 3 + 1], data[117 + i * 3 + 2]), channel_order)
        for i in range(2)
    ]

    # Unpack brightness and speed based on active effect
    if effect == RgbEffect.STREAMING:
        speed = max(1, min(3, data[54] & 0x0F or 2))
        brightness = max(1, min(4, (data[54] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.STEADY:
        speed = 2
        brightness = max(1, min(4, (data[56] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.BREATHING:
        speed = max(1, min(3, data[60] & 0x0F or 2))
        brightness = max(1, min(4, (data[60] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.COLORFUL_TAIL:
        speed = max(1, min(3, data[83] & 0x0F or 2))
        brightness = max(1, min(4, (data[83] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.NEON:
        speed = max(1, min(3, data[84] & 0x0F or 2))
        brightness = max(1, min(4, (data[84] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.COLORFUL_STEADY:
        speed = 2
        brightness = max(1, min(4, (data[85] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.FLICKER:
        speed = max(1, min(3, data[116] & 0x0F or 2))
        brightness = max(1, min(4, (data[116] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.STARS_TWINKLE:
        speed = max(1, min(3, data[123] & 0x0F or 2))
        brightness = max(1, min(4, (data[123] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.WAVE:
        speed = max(1, min(3, data[124] & 0x0F or 2))
        brightness = max(1, min(4, (data[124] >> 4) & 0x0F or 4))
    elif effect == RgbEffect.REACTION:
        speed = max(1, min(3, data[125] & 0x0F or 2))
        brightness = 4
    else:  # OFF
        speed = 2
        brightness = 4

    lod = 1 if data[129] != 0 else 0

    return MouseConfig(
        profile=profile,
        polling_rate=polling_rate,
        active_dpi_stage=raw_active + 1,
        dpi_stages=dpi_stages,
        rgb_effect=effect,
        rgb_brightness=brightness,
        rgb_speed=speed,
        rgb_direction=direction,
        single_color=single_color,
        breathing_colors=breathing_colors,
        zone_colors=zone_colors,
        flicker_colors=flicker_colors,
        lod=lod,
        channel_order=channel_order,
        raw_buffer=bytearray(data),
    )


def serialize_config(cfg: MouseConfig) -> bytearray:
    """Serialize MouseConfig into a 520-byte wire report with write magic."""
    buf = bytearray(cfg.raw_buffer)
    if len(buf) != 520:
        buf = buf.ljust(520, b"\0")

    buf[0] = REPORT_DATA
    buf[1] = (cfg.profile << 4) | 0x01
    buf[2] = 0x00
    buf[3] = CONFIG_WRITE_MAGIC  # 0x7B signals write to firmware

    if cfg.polling_rate in RATE_TO_RAW:
        buf[10] = (buf[10] & 0xF0) | RATE_TO_RAW[cfg.polling_rate]

    act_idx = max(0, min(len(cfg.dpi_stages) - 1, cfg.active_dpi_stage - 1))
    count = min(8, len(cfg.dpi_stages))
    buf[11] = (act_idx << 4) | count

    disabled_mask = 0
    for i, stage in enumerate(cfg.dpi_stages[:8]):
        target_dpi = stage.dpi if stage.dpi in VALID_DPIS else snap_dpi(stage.dpi)
        buf[13 + i] = dpi_to_raw(target_dpi)
        c_off = 29 + i * 3
        hw_c = permute_color_to_hw(stage.color, cfg.channel_order)
        buf[c_off] = hw_c[0]
        buf[c_off + 1] = hw_c[1]
        buf[c_off + 2] = hw_c[2]
        if not stage.enabled:
            disabled_mask |= (1 << i)
    buf[12] = disabled_mask

    # Write active RGB effect ID
    buf[53] = int(cfg.rgb_effect)
    bri = cfg.rgb_brightness & 0x0F
    spd = cfg.rgb_speed & 0x0F

    # Dedicated per-mode register preservation
    if cfg.rgb_effect == RgbEffect.OFF:
        buf[130] = 0x01
    else:
        buf[130] = 0x00

    if cfg.rgb_effect == RgbEffect.STREAMING:
        buf[54] = (bri << 4) | spd
        buf[55] = 1 if cfg.rgb_direction else 0
    elif cfg.rgb_effect == RgbEffect.STEADY:
        buf[56] = (bri << 4) | (buf[56] & 0x0F)
        hw_sc = permute_color_to_hw(cfg.single_color, cfg.channel_order)
        buf[57], buf[58], buf[59] = hw_sc
    elif cfg.rgb_effect == RgbEffect.BREATHING:
        buf[60] = (bri << 4) | spd
        colors = list(cfg.breathing_colors) if cfg.breathing_colors else [cfg.single_color]
        if len(colors) == 1 and cfg.single_color:
            colors = [cfg.single_color]
        b_len = min(7, max(1, len(colors)))
        buf[61] = b_len
        for i, c in enumerate(colors[:b_len]):
            hw_bc = permute_color_to_hw(c, cfg.channel_order)
            buf[62 + i * 3 : 65 + i * 3] = bytes(hw_bc)
    elif cfg.rgb_effect == RgbEffect.COLORFUL_TAIL:
        buf[83] = (bri << 4) | spd
    elif cfg.rgb_effect == RgbEffect.NEON:
        buf[84] = (bri << 4) | spd
    elif cfg.rgb_effect == RgbEffect.COLORFUL_STEADY:
        buf[85] = (bri << 4) | (buf[85] & 0x0F)
        if cfg.zone_colors:
            for i, c in enumerate(cfg.zone_colors[:8]):
                hw_zc = permute_color_to_hw(c, cfg.channel_order)
                buf[86 + i * 3 : 89 + i * 3] = bytes(hw_zc)
    elif cfg.rgb_effect == RgbEffect.FLICKER:
        buf[116] = (bri << 4) | spd
        if cfg.flicker_colors:
            for i, c in enumerate(cfg.flicker_colors[:2]):
                hw_fc = permute_color_to_hw(c, cfg.channel_order)
                buf[117 + i * 3 : 120 + i * 3] = bytes(hw_fc)
    elif cfg.rgb_effect == RgbEffect.STARS_TWINKLE:
        buf[123] = (bri << 4) | spd
    elif cfg.rgb_effect == RgbEffect.WAVE:
        buf[124] = (bri << 4) | spd
    elif cfg.rgb_effect == RgbEffect.REACTION:
        buf[125] = (buf[125] & 0xF0) | spd
        hw_sc = permute_color_to_hw(cfg.single_color, cfg.channel_order)
        buf[57], buf[58], buf[59] = hw_sc

    buf[129] = 1 if cfg.lod == 1 else 0

    return buf
