"""A JPEG header with millions of tiny segments costs bounded time and memory; parsed once."""

import time
import tracemalloc
from pathlib import Path

import pytest

from fastfoto_linux.library import jpeg_exif
from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.jpeg_exif import MAX_SEGMENTS, read_orientation
from fastfoto_linux.library.plan import Action
from tests.library.jpeg_helpers import sideways_jpeg, write_file

REASON = "too-many-segments"
COMMENT = b"\xff\xfe\x00\x02"  # an empty COM segment
RESTART = b"\xff\xd0"  # a marker without a length: no segment, but still a marker to read
MILLION = 1_000_000
MANY = 200_000
SECONDS = 1.0
PEAK_BYTES = 32 * 1024 * 1024
HEADROOM = 20  # the photo's own segments (JFIF, tables, frame header) stay well below this


def padded(data: bytes, filler: bytes, count: int) -> bytes:
    return data[:2] + filler * count + data[2:]


@pytest.mark.timeout(120)
@pytest.mark.parametrize("filler", [COMMENT, RESTART], ids=["comment", "restart"])
def test_a_million_tiny_segments_are_refused_at_once(tmp_path: Path, filler: bytes) -> None:
    write_file(tmp_path, "a.jpg", padded(sideways_jpeg(90, None), filler, MILLION))
    started = time.perf_counter()
    row = decide_file(tmp_path, "a.jpg")
    elapsed = time.perf_counter() - started
    assert (row.action, row.reason) == (Action.SKIP, REASON)
    assert elapsed < SECONDS


@pytest.mark.timeout(120)
def test_many_tiny_segments_cost_bounded_memory(tmp_path: Path) -> None:
    write_file(tmp_path, "a.jpg", padded(sideways_jpeg(90, None), COMMENT, MANY))
    tracemalloc.start()
    try:
        decide_file(tmp_path, "a.jpg")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < PEAK_BYTES


@pytest.mark.timeout(120)
def test_the_reader_itself_refuses_them_with_the_reason() -> None:
    data = padded(sideways_jpeg(90, None), COMMENT, MILLION)
    started = time.perf_counter()
    with pytest.raises(JpegExifError) as caught:
        read_orientation(data)
    assert caught.value.reason == REASON
    assert time.perf_counter() - started < SECONDS


def test_a_photo_just_below_the_limit_is_still_decided(tmp_path: Path) -> None:
    write_file(tmp_path, "a.jpg", padded(sideways_jpeg(90, None), COMMENT, MAX_SEGMENTS - HEADROOM))
    assert decide_file(tmp_path, "a.jpg").action is Action.ROTATE


def test_a_photo_just_above_the_limit_is_skipped(tmp_path: Path) -> None:
    write_file(tmp_path, "a.jpg", padded(sideways_jpeg(90, None), COMMENT, MAX_SEGMENTS + 1))
    row = decide_file(tmp_path, "a.jpg")
    assert (row.action, row.reason) == (Action.SKIP, REASON)


@pytest.mark.parametrize(
    ("deviation", "action", "layouts"),
    [(0, Action.KEEP, 1), (90, Action.ROTATE, 2)],
    ids=["upright: the file", "sideways: the file and the edited copy"],
)
def test_the_layout_of_a_file_is_parsed_once_per_version_of_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, deviation: int, action: Action, layouts: int
) -> None:
    write_file(tmp_path, "a.jpg", sideways_jpeg(deviation, None))
    calls = []
    real = jpeg_exif._layout
    monkeypatch.setattr(jpeg_exif, "_layout", lambda data: calls.append(len(data)) or real(data))
    assert decide_file(tmp_path, "a.jpg").action is action
    assert len(calls) <= layouts
