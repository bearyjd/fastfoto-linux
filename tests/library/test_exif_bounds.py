"""Exif is untrusted: every entry is checked against the block before any parser sees it."""

import struct
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.exif_errors import ExifMalformedError
from fastfoto_linux.library.jpeg_exif import read_orientation, set_orientation
from fastfoto_linux.library.plan import Action
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import rotate_cw, write_file
from tests.library.tiff_helpers import (
    LONG,
    RATIONAL,
    SHORT,
    TiffFixture,
    build_tiff,
    jpeg_with_exif,
)

ENTRY = 12
BYTE = 1
TIME_LIMIT_S = 1.0
HOSTILE_ENTRIES = 4000
HEADER = b"MM\x00*\x00\x00\x00\x08"


def poke(block: bytes, at: int, fmt: str, *values: int) -> bytes:
    packed = struct.pack(">" + fmt, *values)
    return block[:at] + packed + block[at + len(packed) :]


def entry_at(fixture: TiffFixture, ifd: str, index: int) -> int:
    return fixture.where[ifd] + 2 + index * ENTRY


# The base block has an Orientation entry (index 1 of IFD0), so entries after it are bad here.
def corrupt_cases() -> dict[str, Callable[[TiffFixture], bytes]]:
    def ifd0_end(fx: TiffFixture) -> int:
        return fx.where["ifd0"] + 2 + fx.entries_in_ifd0 * ENTRY

    return {
        "ifd0 claims thousands of entries": lambda fx: poke(fx.block, fx.where["ifd0"], "H", 5000),
        "ifd0 offset outside the block": lambda fx: poke(fx.block, 4, "I", len(fx.block) + 100),
        "unknown type after the orientation entry": lambda fx: poke(
            fx.block, entry_at(fx, "ifd0", 2) + 2, "H", 99
        ),
        "type zero": lambda fx: poke(fx.block, entry_at(fx, "ifd0", 2) + 2, "H", 0),
        "value runs past the block": lambda fx: poke(
            fx.block, entry_at(fx, "ifd0", 2) + 4, "I", 0x10000000
        ),
        "count that wraps a 32-bit size": lambda fx: poke(
            poke(fx.block, entry_at(fx, "ifd0", 2) + 2, "H", LONG),
            entry_at(fx, "ifd0", 2) + 4,
            "I",
            0x40000001,
        ),
        "value offset outside the block": lambda fx: poke(
            fx.block, entry_at(fx, "ifd0", 2) + 8, "I", len(fx.block) + 10
        ),
        "value offset inside the tiff header": lambda fx: poke(
            fx.block, entry_at(fx, "ifd0", 2) + 8, "I", 2
        ),
        "next ifd outside the block": lambda fx: poke(
            fx.block, ifd0_end(fx), "I", len(fx.block) + 50
        ),
        "ifd0 points to itself": lambda fx: poke(fx.block, ifd0_end(fx), "I", fx.where["ifd0"]),
        "ifd1 points back to ifd0": lambda fx: poke(
            fx.block, fx.where["ifd1"] + 2 + 2 * ENTRY, "I", fx.where["ifd0"]
        ),
        "exif ifd pointer outside the block": lambda fx: poke(
            fx.block, entry_at(fx, "ifd0", 4) + 8, "I", len(fx.block) + 20
        ),
        "exif ifd pointer loops to ifd0": lambda fx: poke(
            fx.block, entry_at(fx, "ifd0", 4) + 8, "I", fx.where["ifd0"]
        ),
        "bad entry in ifd1": lambda fx: poke(fx.block, fx.where["ifd1"] + 2 + 2, "H", 99),
        "bad entry in the exif ifd": lambda fx: poke(
            fx.block, entry_at(fx, "exif", 1) + 4, "I", 0x7FFFFFFF
        ),
        "exif ifd claims thousands of entries": lambda fx: poke(
            fx.block, fx.where["exif"], "H", 60000
        ),
        "entries run past the block": lambda fx: fx.block[: fx.where["ifd0"] + 30],
        "next pointer missing": lambda fx: fx.block[: ifd0_end(fx) + 2],
    }


@pytest.fixture
def no_pillow_exif(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Pillow's Exif parser was reached before our own checks")

    monkeypatch.setattr(Image.Exif, "load", refuse)
    monkeypatch.setattr(Image.Image, "getexif", refuse)


@pytest.mark.parametrize("action", ["read", "set"])
@pytest.mark.parametrize("name", sorted(corrupt_cases()))
def test_a_malformed_block_is_rejected_before_any_parser_runs(
    name: str, action: str, no_pillow_exif: None
) -> None:
    data = jpeg_with_exif(corrupt_cases()[name](build_tiff(">", (SHORT, 1))))
    with pytest.raises(ExifMalformedError) as raised:
        read_orientation(data) if action == "read" else set_orientation(data, 8)
    assert raised.value.reason == "exif-malformed"


def test_check_skips_a_file_with_a_malformed_block_and_says_why(
    tmp_path: Path, no_pillow_exif: None
) -> None:
    bad = corrupt_cases()["unknown type after the orientation entry"](build_tiff(">", (SHORT, 1)))
    sideways = rotate_cw(load_astronaut(), 90)  # tag 1: shown as stored, so it needs a turn
    write_file(tmp_path, "a.jpg", jpeg_with_exif(bad, sideways))
    row = decide_file(tmp_path, "a.jpg")
    assert (row.action, row.reason) == (Action.SKIP, "exif-malformed")


def hostile_ifd(count: int, kind: int, entry_count: int, value_at: int, data_bytes: int) -> bytes:
    entries = b"".join(
        struct.pack(">HHII", 0x0100 + i % 0x100, kind, entry_count, value_at) for i in range(count)
    )
    ifd = struct.pack(">H", count) + entries + bytes(4)
    return HEADER + ifd + bytes(data_bytes)


def test_thousands_of_entries_with_huge_counts_are_rejected_at_once() -> None:
    block = hostile_ifd(HOSTILE_ENTRIES, RATIONAL, 0x01000000, 8, 0)
    data = jpeg_with_exif(block)
    started = time.perf_counter()
    with pytest.raises(ExifMalformedError):
        read_orientation(data)
    assert time.perf_counter() - started < TIME_LIMIT_S


def test_entries_that_each_fit_but_together_dwarf_the_block_are_rejected_at_once() -> None:
    values = 2 + HOSTILE_ENTRIES * ENTRY + 4 + len(HEADER)
    block = hostile_ifd(HOSTILE_ENTRIES, BYTE, 8000, values, 10000)
    data = jpeg_with_exif(block)
    started = time.perf_counter()
    with pytest.raises(ExifMalformedError):
        read_orientation(data)
    assert time.perf_counter() - started < TIME_LIMIT_S


def test_an_honest_large_ifd_is_still_accepted() -> None:
    count, slot = 300, 8
    first_value = len(HEADER) + 2 + count * ENTRY + 4
    entries = b"".join(
        struct.pack(">HHII", 0x0100 + i, 2, slot, first_value + i * slot) for i in range(count)
    )
    block = HEADER + struct.pack(">H", count) + entries + bytes(4) + bytes(count * slot)
    data = jpeg_with_exif(block)
    assert read_orientation(data) is None
    assert read_orientation(set_orientation(data, 6)) == 6


def test_a_value_that_ends_exactly_at_the_end_of_the_block_is_accepted() -> None:
    fixture = build_tiff(">", None)
    block = poke(fixture.block, entry_at(fixture, "ifd0", 0) + 8, "I", len(fixture.block) - 5)
    assert read_orientation(jpeg_with_exif(block)) is None
