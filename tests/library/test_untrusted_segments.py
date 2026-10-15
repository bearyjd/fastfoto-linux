"""Pillow never sees what a file's own application segments claim, and nothing is lost for it."""

import io
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.jpeg_exif import set_orientation
from fastfoto_linux.library.plan import Action
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import (
    APP1,
    ICC_PAYLOAD,
    XMP_PACKET,
    make_jpeg,
    split_jpeg,
    write_file,
)
from tests.library.untrusted_helpers import sideways, with_mpf_bomb, with_pixel_claim

BOMB_SECONDS = 3.0
BOMB_PEAK_BYTES = 24 * 1024 * 1024
APP_MARKERS = range(0xE0, 0xF0)
MAX_PIXELS_CLAIM = 20_000


class OpenSpy:
    """Stands in for ``Image.open`` and keeps the bytes it was asked to read."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.seen: list[bytes] = []
        self._real = Image.open
        monkeypatch.setattr(Image, "open", self)

    def __call__(self, fp, *args, **kwargs):
        self.seen.append(fp.getvalue() if isinstance(fp, io.BytesIO) else b"")
        return self._real(fp, *args, **kwargs)


def markers_of(data: bytes) -> list[int]:
    return [marker for marker, _ in split_jpeg(data)[0]]


def test_the_decoder_gets_a_copy_without_the_applications_segments_it_does_not_need(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = make_jpeg(load_astronaut(), xmp=True, icc=True)
    bombed, _ = with_mpf_bomb(data, entries=10, count=10)
    write_file(tmp_path, "a.jpg", bombed)
    spy = OpenSpy(monkeypatch)
    assert decide_file(tmp_path, "a.jpg").action is not Action.SKIP
    assert spy.seen
    for seen in spy.seen:
        assert b"MPF\x00" not in seen
        assert ICC_PAYLOAD[:12] not in seen
        assert XMP_PACKET not in seen
        assert 0xDB in markers_of(seen)  # the tables and the picture are all there
        assert 0xC0 in markers_of(seen) or 0xC2 in markers_of(seen)


def test_the_verification_copy_keeps_the_exif_it_has_to_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bombed, _ = with_mpf_bomb(make_jpeg(load_astronaut(), icc=True), entries=10, count=10)
    spy = OpenSpy(monkeypatch)
    edited = set_orientation(bombed, 6)
    assert spy.seen
    assert all(APP1 in markers_of(seen) for seen in spy.seen)
    assert all(b"MPF\x00" not in seen for seen in spy.seen)
    assert b"MPF\x00" in edited  # the file written out still has it


def test_a_file_with_a_huge_mpf_table_is_edited_quickly_in_little_memory() -> None:
    bombed, payload = with_mpf_bomb(make_jpeg(load_astronaut(), icc=True))
    tracemalloc.start()
    started = time.perf_counter()
    try:
        edited = set_orientation(bombed, 6)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert time.perf_counter() - started < BOMB_SECONDS
    assert peak < BOMB_PEAK_BYTES
    assert payload in edited  # the MPF segment and the ICC profile are written out as they were
    assert ICC_PAYLOAD in edited


def test_a_file_with_a_huge_mpf_table_is_still_decided(tmp_path: Path) -> None:
    bombed, _ = with_mpf_bomb(sideways(90))
    write_file(tmp_path, "a.jpg", bombed)
    started = time.perf_counter()
    row = decide_file(tmp_path, "a.jpg")
    assert time.perf_counter() - started < BOMB_SECONDS
    assert row.action is Action.ROTATE


def test_the_segments_of_a_malformed_exif_never_reach_the_decoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = make_jpeg(load_astronaut(), exif=b"Exif\x00\x00MM\x00*\x00\x00\xff\xff")
    spy = OpenSpy(monkeypatch)
    with pytest.raises(JpegExifError):
        set_orientation(broken, 6)
    assert not spy.seen


# --- the pixel limit is the tool's own -------------------------------------------------------


def test_importing_the_command_line_leaves_the_pixel_limit_of_pillow_alone() -> None:
    script = (
        "from PIL import Image\n"
        "before = Image.MAX_IMAGE_PIXELS\n"
        "import fastfoto_linux.cli\n"
        "import fastfoto_linux.library.decide\n"
        "print(before == Image.MAX_IMAGE_PIXELS)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=60
    )
    assert done.stdout.strip() == "True"


def test_a_header_claiming_too_many_pixels_is_skipped_before_anything_is_decoded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    claim = with_pixel_claim(sideways(90), MAX_PIXELS_CLAIM, MAX_PIXELS_CLAIM)
    write_file(tmp_path, "a.jpg", claim)

    def must_not_decode(*_args, **_kwargs):
        raise AssertionError("the image was handed to Pillow")

    monkeypatch.setattr(Image, "open", must_not_decode)
    row = decide_file(tmp_path, "a.jpg")
    assert (row.action, row.reason) == (Action.SKIP, "too-large")


def test_an_ordinary_photo_is_under_the_tools_limit(tmp_path: Path) -> None:
    write_file(tmp_path, "a.jpg", sideways(90))
    assert decide_file(tmp_path, "a.jpg").action is Action.ROTATE
