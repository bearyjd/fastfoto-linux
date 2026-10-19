"""Parse bounded Epson maintenance data, skipping unknown binary values structurally."""

import re
from collections.abc import Iterator

from fastfoto_linux.scanner.power_types import (
    MAX_TIMER_MINUTES,
    PowerSettingsError,
    TimerCapability,
)

Token = bytes | int | None
POWER_KEYS = (b"#SAV", b"#POF")
WORD_BYTES = 4
EXTENDED_NUMBER_BYTES = 8
RANGE_BOUNDS = 2


def tokens(data: bytes, *, require_terminator: bool = False) -> Iterator[Token]:
    """Vendor d3/i7/x7 numbers, four-byte words and aligned h3 binary blocks."""
    offset = 0
    while offset < len(data):
        word = data[offset : offset + 4]
        if len(word) != WORD_BYTES:
            raise PowerSettingsError("The scanner returned incomplete settings data.")
        offset += 4
        if word == b"#---":
            if data[offset:].strip(b" \0"):
                raise PowerSettingsError("The scanner returned data after a terminator.")
            return
        if word[:1] in (b"i", b"x"):
            word += data[offset : offset + 4]
            offset += 4
            if len(word) != EXTENDED_NUMBER_BYTES:
                raise PowerSettingsError("The scanner returned an incomplete number.")
        if word[:1] in (b"d", b"i", b"x"):
            yield _number(word)
        elif word[:1] == b"h":
            if not re.fullmatch(rb"h[0-9A-Fa-f]{3}", word):
                raise PowerSettingsError("The scanner returned an invalid binary length.")
            length = int(word[1:], 16)
            offset += ((length + 3) // 4) * 4
            if offset > len(data):
                raise PowerSettingsError("The scanner returned incomplete binary data.")
            yield None  # Binary bytes are never interpreted as keys or text.
        else:
            yield word
    if require_terminator:
        raise PowerSettingsError("The scanner returned an unterminated settings reply header.")


def _number(word: bytes) -> int:
    pattern = rb"[0-9]{3}" if word[:1] == b"d" else rb"-?[0-9]+"
    if word[:1] == b"x":
        pattern = rb"[0-9A-Fa-f]{7}"
    if not re.fullmatch(pattern, word[1:]):
        raise PowerSettingsError("The scanner returned an invalid numeric setting.")
    return int(word[1:], 16 if word[:1] == b"x" else 10)


def _power_fields(data: bytes) -> dict[bytes, tuple[Token, ...]]:
    fields: dict[bytes, tuple[Token, ...]] = {}
    key: bytes | None = None
    values: list[Token] = []
    for token in tokens(data):
        if isinstance(token, bytes) and token.startswith(b"#"):
            if key in POWER_KEYS:
                fields[key] = tuple(values)
            key, values = token, []
            if key in fields:
                raise PowerSettingsError("The scanner returned a duplicate power setting.")
        else:
            values.append(token)
    if key in POWER_KEYS:
        fields[key] = tuple(values)
    return fields


def parse_capabilities(data: bytes) -> tuple[TimerCapability | None, TimerCapability | None]:
    fields = _power_fields(data)
    return tuple(_capability(fields.get(key)) for key in POWER_KEYS)


def _capability(values: tuple[Token, ...] | None) -> TimerCapability | None:
    if values is None:
        return None
    if not values or any(type(value) is not int for value in values[1:]):
        raise PowerSettingsError("The scanner returned invalid power timer capabilities.")
    numbers = values[1:]
    if not numbers or any(not 0 <= value <= MAX_TIMER_MINUTES for value in numbers):
        raise PowerSettingsError("The scanner returned power timer values outside writable limits.")
    if values[0] == b"RANG" and len(numbers) == RANGE_BOUNDS and numbers[0] <= numbers[1]:
        return TimerCapability(minimum=numbers[0], maximum=numbers[1])
    if values[0] == b"LIST" and len(set(numbers)) == len(numbers):
        return TimerCapability(values=numbers)
    raise PowerSettingsError("The scanner returned an invalid power timer range or list.")


def parse_current(
    data: bytes, capabilities: tuple[TimerCapability | None, TimerCapability | None]
) -> tuple[int | None, int | None]:
    fields = _power_fields(data)
    answer: list[int | None] = []
    for key, capability in zip(POWER_KEYS, capabilities, strict=True):
        values = fields.get(key)
        if capability is None or values is None:
            answer.append(None)
        elif len(values) == 1 and capability.accepts(values[0]):
            answer.append(values[0])
        else:
            raise PowerSettingsError("The scanner returned an invalid current power setting.")
    return tuple(answer)
