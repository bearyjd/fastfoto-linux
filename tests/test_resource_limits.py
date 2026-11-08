"""Resource limits: pixel and size caps refuse before they allocate, and peak memory is bounded.

Each case is cheap: the hostile inputs are a few hundred bytes (a header that claims a huge
picture), so a missing cap shows as a failure or a memory ceiling, not as a minute of work.
"""

import subprocess
import sys
import textwrap
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents.draft_store import MAX_REVIEW_BYTES, read_review
from fastfoto_linux.documents.errors import UnsupportedPageError
from fastfoto_linux.documents.loader import inspect_page, load_page
from fastfoto_linux.library.decide import MAX_IMAGE_PIXELS
from fastfoto_linux.library.jpeg_exif import pixel_count
from fastfoto_linux.photo_edits import PhotoEditError, load_source, parse_recipe
from fastfoto_linux.photo_edits.model import MAX_RECIPE_BYTES, MAX_SOURCE_BYTES, MAX_SOURCE_PIXELS
from fastfoto_linux.photo_edits.png_guard import MAX_CHUNKS, check_png
from fastfoto_linux.pipeline.io import load_frame
from tests.fuzz.jpeg_builders import plain_jpeg, with_size
from tests.photo_edits import png_helpers as h
from tests.photo_edits.helpers import source_at

REPO = Path(__file__).resolve().parent.parent
GROWTH_CEILING_MIB = 50  # a header-only bomb claims gigabytes; the refusal must not allocate them


def _bomb_png(width: int, height: int, colour: int = 0, depth: int = 8) -> bytes:
    """A valid-looking PNG whose header claims ``width`` x ``height`` and holds no pixels."""
    return h.assemble(
        [
            (b"IHDR", h.ihdr(width, height, depth, colour)),
            (b"IDAT", b"\x78\x9c\x03\x00\x00\x00\x00\x01"),
            (b"IEND", b""),
        ]
    )


def _run_peak_rss_mib(code: str) -> float:
    """Peak RSS in MiB of a fresh interpreter that runs ``code`` (measured by getrusage)."""
    script = (
        "import resource\n"
        + textwrap.dedent(code)
        + "\nprint(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
        cwd=REPO,
    )
    return int(result.stdout.split()[-1]) / 1024  # Linux reports KiB


def test_png_master_pixel_bomb_is_refused_before_decoding() -> None:
    with pytest.raises(PhotoEditError, match="too many pixels"):
        check_png(_bomb_png(1 << 16, 1 << 16, colour=2))


def test_png_master_at_the_pixel_cap_passes_the_guard_and_one_past_does_not() -> None:
    assert MAX_SOURCE_PIXELS == 8900 * 10_000
    check_png(_bomb_png(8900, 10_000, colour=2))  # exactly the cap
    check_png(_bomb_png(MAX_SOURCE_PIXELS, 1, colour=2))
    with pytest.raises(PhotoEditError, match="too many pixels"):
        check_png(_bomb_png(MAX_SOURCE_PIXELS + 1, 1, colour=2))  # exactly one pixel past it
    with pytest.raises(PhotoEditError, match="too many pixels"):
        check_png(_bomb_png(8901, 10_000, colour=2))


def test_png_chunk_count_is_capped() -> None:
    chunks = [(b"IHDR", h.ihdr(8, 6)), *[(b"tEXt", b"k\x00v")] * (MAX_CHUNKS + 5)]
    with pytest.raises(PhotoEditError, match="too many chunks"):
        check_png(h.assemble(chunks))


def test_a_stream_of_thousands_of_chunks_is_refused() -> None:
    chunks = [(b"IHDR", h.ihdr(8, 6)), *[(b"tEXt", b"k\x00v")] * 5000]
    with pytest.raises(PhotoEditError, match="too many chunks"):
        check_png(h.assemble(chunks))


def test_jpeg_just_past_the_pixel_cap_is_refused_by_the_cap_not_by_pillow(tmp_path: Path) -> None:
    """Pillow's own guard only fires at 89 478 485 pixels; the editor's cap is 89 000 000."""
    assert MAX_SOURCE_PIXELS < Image.MAX_IMAGE_PIXELS
    path = tmp_path / "photo_0001.jpg"
    path.write_bytes(with_size(plain_jpeg(), 8910, 10_000))  # 89.1 Mpx
    with pytest.raises(PhotoEditError, match="bounded retained original"):
        load_source(path)


def test_jpeg_pixel_bomb_is_refused_by_load_source_and_the_library(tmp_path: Path) -> None:
    bomb = with_size(plain_jpeg(), 65535, 65535)
    assert pixel_count(bomb) > MAX_IMAGE_PIXELS
    path = tmp_path / "photo_0001.jpg"
    path.write_bytes(bomb)
    with pytest.raises(PhotoEditError):
        load_source(path)


def test_source_and_recipe_byte_caps(tmp_path: Path) -> None:
    path = tmp_path / "photo_0001.jpg"
    path.write_bytes(b"\xff\xd8" + b"\x00" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(PhotoEditError, match="too large"):
        load_source(path)
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError):
        parse_recipe(b"{" + b" " * MAX_RECIPE_BYTES, source)


def test_document_page_pixel_bomb_is_refused_with_a_typed_error(tmp_path: Path) -> None:
    page = tmp_path / "page-01.png"
    page.write_bytes(_bomb_png(200_000, 200_000))
    with pytest.raises(UnsupportedPageError):
        inspect_page(page, fallback_dpi=300)
    with pytest.raises(UnsupportedPageError):
        load_page(page, fallback_dpi=300)


def test_scan_frame_pixel_bomb_is_refused_by_pillow_before_allocation(tmp_path: Path) -> None:
    """``pipeline/io.py`` keeps Pillow's own guard on purpose (raises above ~179 Mpx)."""
    frame = tmp_path / "frame.png"
    frame.write_bytes(_bomb_png(20_000, 20_000, colour=2))
    with pytest.raises(Image.DecompressionBombError):
        load_frame(frame, dpi=600)


def test_oversized_review_sidecar_is_refused_before_it_is_read(tmp_path: Path) -> None:
    page = tmp_path / "page-01.png"
    Image.fromarray(np.zeros((8, 8), dtype=np.uint8)).save(page)
    (tmp_path / "review.json").write_bytes(b" " * (MAX_REVIEW_BYTES + 1))
    assert read_review(tmp_path, [page]) is None  # logged and ignored: the pages are analysed again


def _just_over_cap_png(path: Path) -> None:
    """An 8-bit RGB PNG of 89.1 Mpx, all black: about 260 KB on disk, 267 MB if it were decoded.

    The rows are compressed one at a time, so writing it needs almost no memory.
    """
    width, height = 9000, 9900
    assert width * height > MAX_SOURCE_PIXELS
    packer = zlib.compressobj(1)
    row = bytes(1 + 3 * width)  # filter byte 0, then black
    stream = b"".join(packer.compress(row) for _ in range(height)) + packer.flush()
    path.write_bytes(
        h.assemble([(b"IHDR", h.ihdr(width, height, 8, 2)), (b"IDAT", stream), (b"IEND", b"")])
    )


def test_a_png_over_the_pixel_cap_is_refused_without_decoding_it(tmp_path: Path) -> None:
    """The refusal costs almost no memory; decoding the picture would cost 270 MB and more."""
    path = tmp_path / "photo_0001.png"
    _just_over_cap_png(path)
    setup = """
        from pathlib import Path
        from fastfoto_linux.photo_edits import PhotoEditError, load_source
    """
    attack = f"""
        try:
            load_source(Path({str(path)!r}))
        except PhotoEditError:
            pass
        else:
            raise SystemExit("the bomb was accepted")
    """
    baseline = _run_peak_rss_mib(setup)
    attacked = _run_peak_rss_mib(setup + attack)
    assert attacked - baseline < GROWTH_CEILING_MIB
