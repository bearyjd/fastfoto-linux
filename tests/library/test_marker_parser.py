"""The JPEG segment reader is linear in the file size, whatever the file holds."""

import struct
import time

import pytest

from fastfoto_linux.library import fdio
from fastfoto_linux.library.exif_errors import NotAJpegError
from fastfoto_linux.library.jpeg_exif import read_orientation, set_orientation
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import make_jpeg

FILL_BYTES = 16 * 1024 * 1024
SECONDS = 0.2
SOS = b"\xff\xda"


def test_a_huge_run_of_fill_bytes_is_skipped_at_once() -> None:
    data = b"\xff\xd8" + b"\xff" * FILL_BYTES
    for call in (read_orientation, lambda d: set_orientation(d, 6)):
        started = time.perf_counter()
        with pytest.raises(NotAJpegError):
            call(data)
        assert time.perf_counter() - started < SECONDS


def test_fill_bytes_before_a_marker_are_allowed_and_kept() -> None:
    data = make_jpeg(load_astronaut())
    scan = data.index(SOS)
    padded = data[:scan] + b"\xff" * 5000 + data[scan:]
    edited = set_orientation(padded, 6)
    assert read_orientation(edited) == 6
    assert edited.endswith(padded[scan:])  # the scan and what precedes it are as they were


def test_the_size_limit_for_a_photo_is_128_mib() -> None:
    assert fdio.MAX_FILE_BYTES == 128 * 1024 * 1024


def test_a_segment_longer_than_the_file_is_still_refused() -> None:
    data = b"\xff\xd8\xff\xe1" + struct.pack(">H", 5000) + b"short"
    with pytest.raises(NotAJpegError):
        read_orientation(data)
