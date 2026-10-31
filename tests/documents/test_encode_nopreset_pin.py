"""Pins today's document page encoding for the no-preset path (presets must not change it)."""

import io

from PIL import Image

from fastfoto_linux.documents.encode import encode_page
from fastfoto_linux.documents.modes import ColourMode
from tests.doc_synth import paper_scene, with_text
from tests.documents.helpers import bw_page, colour_page, grey_page

DPI = 100


def page_scene():
    page = paper_scene(dpi=DPI)
    for row in range(4):
        page = with_text(page, 25, 30 + row * 10, 25)
    return page


def legacy_jpeg(pixels, dpi: int) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "JPEG", quality=85, dpi=(dpi, dpi))
    return buffer.getvalue()


def test_colour_page_bytes_equal_the_legacy_jpeg() -> None:
    page = colour_page(page_scene())

    assert encode_page(page, ColourMode.COLOUR).data == legacy_jpeg(page.pixels, DPI)


def test_grey_page_bytes_equal_the_legacy_jpeg() -> None:
    page = grey_page(page_scene())

    assert encode_page(page, ColourMode.GREY).data == legacy_jpeg(page.pixels, DPI)


def test_black_and_white_page_is_group4_at_native_size() -> None:
    page = bw_page(page_scene())
    encoded = encode_page(page, ColourMode.BW)

    picture = Image.open(io.BytesIO(encoded.data))
    assert picture.format == "TIFF"
    assert picture.info["compression"] == "group4"
    assert picture.size == (page.pixels.shape[1], page.pixels.shape[0])
    assert encoded.dpi == DPI
