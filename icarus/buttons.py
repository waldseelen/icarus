"""Button mapping block (report 0x04, command 0x12/0x22) parser and serializer.

Translates the mouse onboard flash button configuration table into structured
Python objects and serializes back to the Sinowealth 88-byte wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

BUTTON_BLOCK_SIZE = 88
BUTTON_WRITE_MAGIC = 0x50
REPORT_DATA = 0x04

# Physical button to hardware slot routing:
# In hardware wiring (Cfg.ini), physical K4 (Forward) is wired to Pin 5 (Slot 5),
# and physical K5 (Back) is wired to Pin 4 (Slot 4).
PHYSICAL_TO_SLOT = {1: 1, 2: 2, 3: 3, 4: 5, 5: 4, 6: 6, 7: 7, 8: 8, 9: 9}
SLOT_TO_PHYSICAL = {1: 1, 2: 2, 3: 3, 4: 5, 5: 4, 6: 6, 7: 7, 8: 8, 9: 9}

# Physical button labels for Gamepower Icarus (9 buttons)
BUTTON_NAMES = {
    1: "K1 (Left Click)",
    2: "K2 (Right Click)",
    3: "K3 (Middle Click)",
    4: "K4 (Forward)",
    5: "K5 (Back)",
    6: "K6 (DPI Up)",
    7: "K7 (DPI Down)",
    8: "K8 (Fire Key)",
    9: "K9 (Sniper / DPI Lock)",
}

# Vendor action codes
ACTION_FIRE = 0x17
ACTION_SNIPER = 0xA6


class ButtonType(IntEnum):
    DISABLED = 0x00
    MOUSE_CLICK = 0x11
    WHEEL = 0x12
    KEY = 0x21
    MULTIMEDIA = 0x22
    REPEATED = 0x31  # Fire Key burst action
    FIRE = 0x31  # Alias
    MULTI_CLICK = 0x33  # Double Click / Triple Click
    DPI_SWITCH = 0x41
    DPI_LOCK = 0x42  # Sniper / DPI Lock
    SNIPER = 0x42  # Alias
    SPECIAL = 0x50
    MACRO = 0x70


class MultiClickCode(IntEnum):
    DOUBLE = 0x01
    TRIPLE = 0x02


# Multimedia & Consumer actions (btype = 0x22): (data0, data1, data2)
MULTIMEDIA_ACTIONS: dict[str, tuple[int, int, int]] = {
    "next_track": (0x01, 0x00, 0x00),
    "prev_track": (0x02, 0x00, 0x00),
    "stop": (0x04, 0x00, 0x00),
    "play_pause": (0x08, 0x00, 0x00),
    "mute": (0x10, 0x00, 0x00),
    "volume_up": (0x40, 0x00, 0x00),
    "volume_down": (0x80, 0x00, 0x00),
    "media_player": (0x00, 0x01, 0x00),
    "explorer": (0x00, 0x02, 0x00),
    "mail": (0x00, 0x10, 0x00),
    "calculator": (0x00, 0x20, 0x00),
    "web_search": (0x00, 0x00, 0x01),
    "web_home": (0x00, 0x00, 0x02),
    "web_back": (0x00, 0x00, 0x04),
    "web_forward": (0x00, 0x00, 0x08),
    "web_stop": (0x00, 0x00, 0x10),
    "web_refresh": (0x00, 0x00, 0x20),
    "web_favorites": (0x00, 0x00, 0x40),
}

MULTIMEDIA_NAMES: dict[tuple[int, int, int], str] = {
    (0x01, 0x00, 0x00): "Next Track",
    (0x02, 0x00, 0x00): "Previous Track",
    (0x04, 0x00, 0x00): "Stop",
    (0x08, 0x00, 0x00): "Play / Pause",
    (0x10, 0x00, 0x00): "Mute",
    (0x40, 0x00, 0x00): "Volume Up",
    (0x80, 0x00, 0x00): "Volume Down",
    (0x00, 0x01, 0x00): "Media Player",
    (0x00, 0x02, 0x00): "File Explorer",
    (0x00, 0x10, 0x00): "Email",
    (0x00, 0x20, 0x00): "Calculator",
    (0x00, 0x00, 0x01): "Web Search",
    (0x00, 0x00, 0x02): "Web Home",
    (0x00, 0x00, 0x04): "Web Back",
    (0x00, 0x00, 0x08): "Web Forward",
    (0x00, 0x00, 0x10): "Web Stop",
    (0x00, 0x00, 0x20): "Web Refresh",
    (0x00, 0x00, 0x40): "Web Favorites",
}

# Special Hardware Toggles (btype = 0x50): data0
SPECIAL_HW_ACTIONS: dict[str, int] = {
    "profile_switch": 0x01,
    "polling_rate_switch": 0x02,
    "lighting_toggle": 0x04,
    "lighting_effect_switch": 0x06,
    "lighting_color_switch": 0x07,
    "lighting_speed_switch": 0x08,
    "lighting_brightness_switch": 0x09,
}

SPECIAL_HW_NAMES: dict[int, str] = {
    0x01: "Switch Profile (Mode)",
    0x02: "Switch Polling Rate",
    0x04: "Lighting ON / OFF",
    0x06: "Switch Lighting Effect",
    0x07: "Switch Lighting Color",
    0x08: "Switch Lighting Speed",
    0x09: "Switch Lighting Brightness",
}


class ClickCode(IntEnum):
    LEFT = 0x01
    RIGHT = 0x02
    MIDDLE = 0x04
    BACK = 0x08
    FORWARD = 0x10


class DpiSwitchCode(IntEnum):
    CYCLE = 0x00
    UP = 0x01
    DOWN = 0x02


@dataclass
class ButtonBinding:
    slot: int  # 1..20
    btype: ButtonType
    data0: int = 0
    data1: int = 0
    data2: int = 0

    @property
    def physical_button(self) -> int:
        return SLOT_TO_PHYSICAL.get(self.slot, self.slot)

    @property
    def name(self) -> str:
        return BUTTON_NAMES.get(self.physical_button, f"Button {self.slot}")

    def summary(self) -> str:
        if self.btype == ButtonType.MOUSE_CLICK:
            clicks = {
                ClickCode.LEFT: "Left Click",
                ClickCode.RIGHT: "Right Click",
                ClickCode.MIDDLE: "Middle Click",
                ClickCode.BACK: "Back",
                ClickCode.FORWARD: "Forward",
            }
            return clicks.get(ClickCode(self.data0), f"Click({self.data0:#04x})")
        if self.btype == ButtonType.DPI_SWITCH:
            sw = {
                DpiSwitchCode.CYCLE: "DPI Cycle",
                DpiSwitchCode.UP: "DPI +",
                DpiSwitchCode.DOWN: "DPI -",
            }
            return sw.get(DpiSwitchCode(self.data0), f"DPI Switch({self.data0:#04x})")
        if self.btype in (ButtonType.DPI_LOCK, ButtonType.SNIPER):
            return f"Sniper / DPI Lock (stage={self.data0 or 1})"
        if self.btype in (ButtonType.REPEATED, ButtonType.FIRE):
            return f"Fire Key (burst, repeat={self.data1 or 3}, interval={self.data2 or 30}ms)"
        if self.btype == ButtonType.KEY:
            mods = []
            if self.data0 & 0x01:
                mods.append("Ctrl")
            if self.data0 & 0x02:
                mods.append("Shift")
            if self.data0 & 0x04:
                mods.append("Alt")
            if self.data0 & 0x08:
                mods.append("Super")
            key_str = f"HID({self.data1:#04x})"
            return "+".join(mods + [key_str]) if mods else key_str
        if self.btype == ButtonType.MACRO:
            modes = {1: "REPEAT_COUNT", 2: "UNTIL_RELEASE", 4: "UNTIL_ANY_KEY"}
            mode_str = modes.get(self.data1, f"mode={self.data1}")
            return f"Macro #{self.data0} ({mode_str}, count={self.data2})"
        if self.btype == ButtonType.MULTI_CLICK:
            clicks = {MultiClickCode.DOUBLE: "Double Click", MultiClickCode.TRIPLE: "Triple Click"}
            return clicks.get(MultiClickCode(self.data0), f"MultiClick({self.data0})")
        if self.btype == ButtonType.MULTIMEDIA:
            key = (self.data0, self.data1, self.data2)
            return MULTIMEDIA_NAMES.get(key, f"Media({self.data0:#02x},{self.data1:#02x},{self.data2:#02x})")
        if self.btype == ButtonType.SPECIAL:
            return SPECIAL_HW_NAMES.get(self.data0, f"Special({self.data0:#04x})")
        if self.btype == ButtonType.DISABLED:
            return "Disabled"
        return f"{self.btype.name}({self.data0:#02x},{self.data1:#02x})"


def make_multimedia_binding(slot: int, action: str) -> ButtonBinding:
    """Create multimedia or consumer action binding."""
    key = MULTIMEDIA_ACTIONS.get(action.lower(), (0x01, 0x00, 0x00))
    return ButtonBinding(slot=slot, btype=ButtonType.MULTIMEDIA, data0=key[0], data1=key[1], data2=key[2])


def make_special_binding(slot: int, action: str | int) -> ButtonBinding:
    """Create hardware toggle binding (profile, polling rate, lighting)."""
    code = SPECIAL_HW_ACTIONS.get(action.lower()) if isinstance(action, str) else int(action)
    return ButtonBinding(slot=slot, btype=ButtonType.SPECIAL, data0=code or 0x01)


def make_multiclick_binding(slot: int, count: int = 2) -> ButtonBinding:
    """Create hardware double or triple click binding."""
    val = MultiClickCode.TRIPLE if count >= 3 else MultiClickCode.DOUBLE
    return ButtonBinding(slot=slot, btype=ButtonType.MULTI_CLICK, data0=int(val))


def make_fire_binding(slot: int, repeat: int = 3, interval_ms: int = 30) -> ButtonBinding:
    """Create Fire Key burst binding (data0=1 for Left Click, data1=repeat, data2=interval)."""
    return ButtonBinding(
        slot=slot,
        btype=ButtonType.REPEATED,
        data0=ClickCode.LEFT,
        data1=max(1, min(255, repeat)),
        data2=max(5, min(255, interval_ms)),
    )


def make_sniper_binding(slot: int, stage: int = 1) -> ButtonBinding:
    """Create Sniper / DPI Lock binding (data0=target stage 1..8 while held)."""
    return ButtonBinding(
        slot=slot,
        btype=ButtonType.DPI_LOCK,
        data0=max(1, min(8, stage)),
        data1=0,
        data2=0,
    )


def make_macro_binding(
    slot: int, slot_index: int, loop_mode: int = 1, repeat_count: int = 1
) -> ButtonBinding:
    """Create Macro binding: type=0x70, data0=slot (1..16), data1=loop_mode, data2=repeat_count."""
    return ButtonBinding(
        slot=slot,
        btype=ButtonType.MACRO,
        data0=max(1, min(16, slot_index)),
        data1=loop_mode,
        data2=max(1, min(255, repeat_count)),
    )


@dataclass
class ButtonTable:
    profile: int
    buttons: list[ButtonBinding] = field(default_factory=list)
    raw_buffer: bytearray = field(default_factory=lambda: bytearray(520))


def parse_buttons(data: bytes | bytearray) -> ButtonTable:
    if len(data) < BUTTON_BLOCK_SIZE or data[0] != REPORT_DATA:
        raise ValueError(f"Invalid button report header (len={len(data)})")

    cmd = data[1]
    profile = (cmd >> 4) & 0x0F
    if profile not in (1, 2):
        raise ValueError(f"Unsupported profile id in buttons: {profile}")

    buttons: list[ButtonBinding] = []
    # Up to 20 slots, 4 bytes each starting at offset 8
    for i in range(20):
        off = 8 + i * 4
        btype_val = data[off]
        btype = (
            ButtonType(btype_val)
            if btype_val in ButtonType._value2member_map_
            else ButtonType.DISABLED
        )
        buttons.append(
            ButtonBinding(
                slot=i + 1,
                btype=btype,
                data0=data[off + 1],
                data1=data[off + 2],
                data2=data[off + 3],
            )
        )

    return ButtonTable(
        profile=profile,
        buttons=buttons,
        raw_buffer=bytearray(data),
    )


def serialize_buttons(table: ButtonTable) -> bytearray:
    buf = bytearray(table.raw_buffer)
    if len(buf) != 520:
        buf = buf.ljust(520, b"\0")

    buf[0] = REPORT_DATA
    buf[1] = (table.profile << 4) | 0x02
    buf[2] = 0x00
    buf[3] = BUTTON_WRITE_MAGIC  # 0x50 signals button write to firmware

    for b in table.buttons[:20]:
        off = 8 + (b.slot - 1) * 4
        buf[off] = int(b.btype)
        buf[off + 1] = b.data0 & 0xFF
        buf[off + 2] = b.data1 & 0xFF
        buf[off + 3] = b.data2 & 0xFF

    return buf
