"""Reading page files: RGB, 8-bit grey and 1-bit PNGs; everything else is refused clearly."""

import struct
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents.errors import UnsupportedPageError
from fastfoto_linux.documents.loader import inspect_page, load_page
from fastfoto_linux.documents.modes import ColourMode
from tests.doc_synth import write_png

RNG = np.random.default_rng(7)
RGB = RNG.integers(0, 256, (40, 30, 3), dtype=np.uint8)
GREY = RNG.integers(0, 256, (40, 30), dtype=np.uint8)
BILEVEL = np.where(RNG.random((40, 30)) > 0.5, 255, 0).astype(np.uint8)


def test_an_rgb_png_loads_as_colour_with_its_resolution(tmp_path: Path) -> None:
    page = load_page(write_png(tmp_path / "p.png", RGB, dpi=300))
    assert page.kind is ColourMode.COLOUR
    assert page.dpi == 300
    assert page.pixels.shape == (40, 30, 3)
    assert page.pixels.dtype == np.uint8
    assert np.array_equal(page.pixels, RGB)


def test_an_8_bit_grey_png_loads_as_grey(tmp_path: Path) -> None:
    page = load_page(write_png(tmp_path / "p.png", GREY, dpi=200))
    assert page.kind is ColourMode.GREY
    assert page.dpi == 200
    assert page.pixels.shape == (40, 30)
    assert np.array_equal(page.pixels, GREY)


def test_a_1_bit_png_loads_as_black_and_white_with_values_0_and_255(tmp_path: Path) -> None:
    page = load_page(write_png(tmp_path / "p.png", BILEVEL, dpi=600, mode="1"))
    assert page.kind is ColourMode.BW
    assert page.dpi == 600
    assert page.pixels.dtype == np.uint8
    assert np.array_equal(page.pixels, BILEVEL)


def test_a_resolution_written_as_pixels_per_metre_is_rounded_to_whole_dpi(tmp_path: Path) -> None:
    path = tmp_path / "p.png"
    Image.fromarray(RGB).save(path, "PNG", dpi=(299.9994, 299.9994))  # 11811 px/m
    assert Image.open(path).info["dpi"][0] != 300  # what Pillow reads back is not whole
    assert load_page(path).dpi == 300
    assert inspect_page(path).dpi == 300


def test_inspect_reports_kind_resolution_and_size_without_decoding(tmp_path: Path) -> None:
    info = inspect_page(write_png(tmp_path / "p.png", GREY, dpi=300))
    assert (info.kind, info.dpi, info.width, info.height) == (ColourMode.GREY, 300, 30, 40)


def test_a_page_without_a_resolution_needs_the_fallback(tmp_path: Path) -> None:
    path = write_png(tmp_path / "bare.png", RGB, dpi=None)
    with pytest.raises(UnsupportedPageError, match=r"bare\.png.*resolution"):
        load_page(path)
    with pytest.raises(UnsupportedPageError, match="resolution"):
        inspect_page(path)
    assert load_page(path, fallback_dpi=150).dpi == 150
    assert inspect_page(path, fallback_dpi=150).dpi == 150


def test_the_fallback_never_overrides_a_resolution_the_file_has(tmp_path: Path) -> None:
    path = write_png(tmp_path / "p.png", RGB, dpi=300)
    assert load_page(path, fallback_dpi=150).dpi == 300


def test_unequal_horizontal_and_vertical_resolution_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "p.png"
    Image.fromarray(RGB).save(path, "PNG", dpi=(300, 200))
    with pytest.raises(UnsupportedPageError, match=r"p\.png.*(differ|unequal|different)"):
        load_page(path)


@pytest.mark.parametrize("dpi", [1, 10, 100000])
def test_an_absurd_resolution_is_refused(tmp_path: Path, dpi: int) -> None:
    path = tmp_path / "p.png"
    Image.fromarray(RGB).save(path, "PNG", dpi=(dpi, dpi))
    with pytest.raises(UnsupportedPageError, match="resolution"):
        load_page(path)


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P", "I;16"])
def test_other_png_modes_are_refused_by_name(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "odd.png"
    Image.new(mode, (8, 8)).save(path, "PNG", dpi=(300, 300))
    with pytest.raises(UnsupportedPageError, match=rf"odd\.png.*{mode}"):
        load_page(path)
    with pytest.raises(UnsupportedPageError, match=r"odd\.png"):
        inspect_page(path)


def test_a_jpeg_is_not_a_png(tmp_path: Path) -> None:
    path = tmp_path / "photo.png"  # the name lies
    Image.fromarray(RGB).save(path, "JPEG", dpi=(300, 300))
    with pytest.raises(UnsupportedPageError, match=r"photo\.png.*PNG"):
        load_page(path)


def test_a_file_that_is_not_an_image_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "junk.png"
    path.write_bytes(b"not a picture at all")
    with pytest.raises(UnsupportedPageError, match=r"junk\.png"):
        load_page(path)


def test_a_truncated_png_passes_the_header_check_but_not_the_decode(tmp_path: Path) -> None:
    path = write_png(tmp_path / "cut.png", RGB, dpi=300)
    path.write_bytes(path.read_bytes()[:-60])
    inspect_page(path)  # the header is fine
    with pytest.raises(UnsupportedPageError, match=r"cut\.png"):
        load_page(path)


def test_a_png_that_claims_a_huge_size_is_refused_not_decoded(tmp_path: Path) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 60000, 60000, 8, 2, 0, 0, 0)
    path = tmp_path / "bomb.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )
    with pytest.raises(UnsupportedPageError, match=r"bomb\.png"):
        inspect_page(path, fallback_dpi=300)


def test_loading_does_not_touch_the_file(tmp_path: Path) -> None:
    path = write_png(tmp_path / "p.png", RGB, dpi=300)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    load_page(path)
    inspect_page(path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
