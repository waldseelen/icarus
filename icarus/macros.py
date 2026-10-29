"""Macro serialization (MacProtocol=2, report 0x04, command 0x30).

Translates key and button sequences into the 3-byte Sinowealth onboard macro
event stream and serializes into the 520-byte flash write frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

REPORT_DATA = 0x04
CMD_MACRO = 0x30
MACRO_WRITE_FLAG = 0x02
MAX_MACRO_EVENTS = 168

# Common USB HID Keyboard usages
HID_KEY_MAP = {
    "a": 0x04,
    "b": 0x05,
    "c": 0x06,
    "d": 0x07,
    "e": 0x08,
    "f": 0x09,
    "g": 0x0A,
    "h": 0x0B,
    "i": 0x0C,
    "j": 0x0D,
    "k": 0x0E,
    "l": 0x0F,
    "m": 0x10,
    "n": 0x11,
    "o": 0x12,
    "p": 0x13,
    "q": 0x14,
    "r": 0x15,
    "s": 0x16,
    "t": 0x17,
    "u": 0x18,
    "v": 0x19,
    "w": 0x1A,
    "x": 0x1B,
    "y": 0x1C,
    "z": 0x1D,
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
    "enter": 0x28,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "f1": 0x3A,
    "f2": 0x3B,
    "f3": 0x3C,
    "f4": 0x3D,
    "f5": 0x3E,
    "f6": 0x3F,
    "f7": 0x40,
    "f8": 0x41,
    "f9": 0x42,
    "f10": 0x43,
    "f11": 0x44,
    "f12": 0x45,
    "shift": 0xE1,
    "ctrl": 0xE0,
    "alt": 0xE2,
    "super": 0xE3,
}
NAME_BY_HID = {v: k for k, v in HID_KEY_MAP.items()}


class MacroCmd(IntEnum):
    BTN_PRESS = 0x10
    BTN_DOWN = 0x10  # Alias
    WHEEL = 0x20
    MOVE_X = 0x30
    MOVE_Y = 0x40
    KEY_PRESS = 0x50
    KEY_DOWN = 0x50  # Alias
    BTN_RELEASE = 0x90
    BTN_UP = 0x90  # Alias
    KEY_RELEASE = 0xD0
    KEY_UP = 0xD0  # Alias


class MacroLoopMode(IntEnum):
    REPEAT_COUNT = 1
    UNTIL_RELEASE = 2
    UNTIL_ANY_KEY = 4


@dataclass
class MacroEvent:
    cmd: MacroCmd
    code: int  # key HID code, mouse button bitmask, or signed wheel/move delta
    delay_ms: int = 10  # 1..4095 ms

    def summary(self) -> str:
        if self.cmd in (MacroCmd.KEY_PRESS, MacroCmd.KEY_RELEASE):
            action = "KeyDown" if self.cmd in (MacroCmd.KEY_PRESS, MacroCmd.KEY_DOWN) else "KeyUp"
            k = NAME_BY_HID.get(self.code, f"Key({self.code:#02x})")
            return f"{action}({k}, delay={self.delay_ms}ms)"
        if self.cmd in (MacroCmd.BTN_PRESS, MacroCmd.BTN_RELEASE):
            action = "BtnDown" if self.cmd in (MacroCmd.BTN_PRESS, MacroCmd.BTN_DOWN) else "BtnUp"
            return f"{action}(mask={self.code:#02x}, delay={self.delay_ms}ms)"
        if self.cmd == MacroCmd.WHEEL:
            delta = int.from_bytes(bytes([self.code & 0xFF]), "little", signed=True)
            return f"Wheel(delta={delta}, delay={self.delay_ms}ms)"
        if self.cmd == MacroCmd.MOVE_X:
            dx = int.from_bytes(bytes([self.code & 0xFF]), "little", signed=True)
            return f"MoveX(dx={dx}, delay={self.delay_ms}ms)"
        if self.cmd == MacroCmd.MOVE_Y:
            dy = int.from_bytes(bytes([self.code & 0xFF]), "little", signed=True)
            return f"MoveY(dy={dy}, delay={self.delay_ms}ms)"
        return f"Event({self.cmd.name}, code={self.code:#02x}, delay={self.delay_ms}ms)"


@dataclass
class OnboardMacro:
    index: int  # 1..16
    events: list[MacroEvent] = field(default_factory=list)

    def add_key_tap(self, key_name_or_code: str | int, delay_ms: int = 15) -> None:
        code = (
            HID_KEY_MAP[key_name_or_code.lower()]
            if isinstance(key_name_or_code, str)
            else key_name_or_code
        )
        self.events.append(MacroEvent(MacroCmd.KEY_PRESS, code, delay_ms))
        self.events.append(MacroEvent(MacroCmd.KEY_RELEASE, code, delay_ms))

    def add_btn_click(self, btn_num: int = 1, delay_ms: int = 15) -> None:
        mask = 1 << (btn_num - 1)
        self.events.append(MacroEvent(MacroCmd.BTN_PRESS, mask, delay_ms))
        self.events.append(MacroEvent(MacroCmd.BTN_RELEASE, mask, delay_ms))

    def add_wheel(self, delta: int = 1, delay_ms: int = 15) -> None:
        code = delta & 0xFF
        self.events.append(MacroEvent(MacroCmd.WHEEL, code, delay_ms))

    def add_move(self, dx: int = 0, dy: int = 0, delay_ms: int = 15) -> None:
        if dx != 0:
            self.events.append(MacroEvent(MacroCmd.MOVE_X, dx & 0xFF, delay_ms))
        if dy != 0:
            self.events.append(MacroEvent(MacroCmd.MOVE_Y, dy & 0xFF, delay_ms))


def serialize_macro(macro: OnboardMacro) -> bytearray:
    """Serialize OnboardMacro into a 520-byte report-0x04 frame (MacProtocol=2)."""
    if not (1 <= macro.index <= 16):
        raise ValueError(f"Macro slot index {macro.index} out of range (1..16)")
    if len(macro.events) > MAX_MACRO_EVENTS:
        raise ValueError(
            f"Too many macro events: {len(macro.events)} > {MAX_MACRO_EVENTS}"
        )

    buf = bytearray(520)
    buf[0] = REPORT_DATA
    buf[1] = CMD_MACRO
    buf[2] = MACRO_WRITE_FLAG
    # Bytes 3..7 remain 0
    buf[8] = macro.index & 0xFF
    buf[9] = (len(macro.events) >> 8) & 0xFF
    buf[10] = len(macro.events) & 0xFF

    for i, ev in enumerate(macro.events):
        off = 11 + i * 3
        delay = max(1, min(4095, ev.delay_ms))
        cmd_base = int(ev.cmd) & 0xF0
        buf[off] = cmd_base | ((delay >> 8) & 0x0F)
        buf[off + 1] = delay & 0xFF
        buf[off + 2] = ev.code & 0xFF

    return buf


serialize_macro_packet = serialize_macro


def parse_macro(data: bytes | bytearray) -> OnboardMacro:
    """Parse a 520-byte macro frame with 12-bit delay framing."""
    if len(data) < 11 or data[0] != REPORT_DATA or data[1] != CMD_MACRO:
        raise ValueError("Invalid macro frame header")

    macro_idx = data[8]
    count = (data[9] << 8) | data[10]
    events: list[MacroEvent] = []

    for i in range(min(count, MAX_MACRO_EVENTS)):
        off = 11 + i * 3
        raw_cmd = data[off]
        cmd_type = raw_cmd & 0xF0
        delay_high = raw_cmd & 0x0F
        delay_low = data[off + 1]
        delay_ms = (delay_high << 8) | delay_low
        code = data[off + 2]
        if cmd_type in MacroCmd._value2member_map_:
            events.append(MacroEvent(cmd=MacroCmd(cmd_type), code=code, delay_ms=delay_ms))

    return OnboardMacro(index=macro_idx, events=events)
