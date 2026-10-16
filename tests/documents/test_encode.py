"""One page encoded for the PDF: JPEG for colour and grey, lossless CCITT G4 for black and white."""

import io

import numpy as np
from PIL import Image

from fastfoto_linux.documents.encode import JPEG_QUALITY, encode_page
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from tests.doc_synth import Scene, paper_scene, to_grey, with_text
from tests.documents.helpers import bw_page, colour_page, grey_page

C, G, B = ColourMode.COLOUR, ColourMode.GREY, ColourMode.BW
DPI = 100
INK_BELOW = 100


def scene() -> Scene:
    page = paper_scene(dpi=DPI)
    for row in range(5):
        page = with_text(page, 25, 30 + row * 10, 25)
    return page


def decode(data: bytes) -> Image.Image:
    picture = Image.open(io.BytesIO(data))
    picture.load()
    return picture


def test_a_colour_page_becomes_an_rgb_jpeg_close_to_the_original() -> None:
    page = colour_page(scene())
    encoded = encode_page(page, C)
    assert encoded.mode is C
    assert encoded.data[:2] == b"\xff\xd8"
    picture = decode(encoded.data)
    assert picture.format == "JPEG"
    assert picture.mode == "RGB"
    assert picture.size == (page.pixels.shape[1], page.pixels.shape[0])
    assert round(picture.info["dpi"][0]) == DPI
    assert np.abs(np.asarray(picture).astype(int) - page.pixels).mean() < 4


def test_a_colour_page_can_be_written_in_grey() -> None:
    page = colour_page(scene())
    encoded = encode_page(page, G)
    picture = decode(encoded.data)
    assert (encoded.mode, picture.format, picture.mode) == (G, "JPEG", "L")
    assert np.abs(np.asarray(picture).astype(int) - to_grey(page.pixels)).mean() < 4


def test_a_grey_page_asked_for_in_colour_stays_grey() -> None:
    encoded = encode_page(grey_page(scene()), C)
    assert encoded.mode is G
    assert decode(encoded.data).mode == "L"


def test_a_jpeg_is_written_at_the_documented_quality() -> None:
    page = colour_page(scene())
    reference = io.BytesIO()
    Image.fromarray(page.pixels).save(reference, "JPEG", quality=JPEG_QUALITY)
    assert JPEG_QUALITY == 85
    assert (
        decode(encode_page(page, C).data).quantization == decode(reference.getvalue()).quantization
    )


def test_colour_to_black_and_white_is_a_group_4_tiff_with_ink_black_and_paper_white() -> None:
    page = colour_page(scene())
    encoded = encode_page(page, B)
    picture = decode(encoded.data)
    assert encoded.mode is B
    assert (picture.format, picture.mode) == ("TIFF", "1")
    assert picture.info["compression"] == "group4"
    white = np.asarray(picture)
    ink = to_grey(page.pixels) < INK_BELOW
    assert (~white[ink]).mean() > 0.95
    assert white[~ink].mean() > 0.999


def test_a_page_that_was_already_one_bit_keeps_every_pixel() -> None:
    rng = np.random.default_rng(4)
    pixels = np.where(rng.random((120, 90)) > 0.3, 255, 0).astype(np.uint8)
    encoded = encode_page(LoadedPage(pixels, B, DPI), C)  # asking for more changes nothing
    assert encoded.mode is B
    assert np.array_equal(np.asarray(decode(encoded.data)), pixels == 255)


def test_a_one_bit_page_with_big_solid_areas_is_not_thresholded_again() -> None:
    pixels = np.full((200, 160), 255, np.uint8)
    pixels[20:150, 20:120] = 0  # a black area far bigger than any threshold window
    encoded = encode_page(LoadedPage(pixels, B, DPI), B)
    assert np.array_equal(np.asarray(decode(encoded.data)), pixels == 255)


def test_a_bilevel_text_page_survives_the_round_trip() -> None:
    page = bw_page(scene())
    decoded = np.asarray(decode(encode_page(page, B).data))
    assert np.array_equal(decoded, page.pixels == 255)


def test_the_encoded_page_records_its_size_resolution_and_mode() -> None:
    page = grey_page(scene())
    encoded = encode_page(page, G)
    assert (encoded.width, encoded.height) == (page.pixels.shape[1], page.pixels.shape[0])
    assert encoded.dpi == DPI


def test_encoding_does_not_modify_the_page() -> None:
    page = colour_page(scene())
    before = page.pixels.copy()
    for requested in (C, G, B):
        encode_page(page, requested)
    assert np.array_equal(page.pixels, before)
