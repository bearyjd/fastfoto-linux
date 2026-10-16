"""Assemble encoded pages into one PDF that embeds them as they are."""

from datetime import UTC, datetime

import numpy as np
import pytest

from fastfoto_linux.documents.encode import EncodedPage, encode_page
from fastfoto_linux.documents.errors import DocumentError
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.pdf import PRODUCER, assemble_pdf
from tests.doc_synth import Scene, paper_scene, with_text
from tests.documents.helpers import (
    FIXED_TIME,
    bw_page,
    colour_page,
    expected_points,
    grey_page,
    image_object,
    page_size_pt,
    pdf_pixels,
    reader,
)

C, G, B = ColourMode.COLOUR, ColourMode.GREY, ColourMode.BW


def scene(dpi: int = 100) -> Scene:
    page = paper_scene(dpi=dpi)
    for row in range(4):
        page = with_text(page, 25, 30 + row * 10, 25)
    return page


def make(pages, *, title: str = "Taxes", created: datetime = FIXED_TIME) -> bytes:
    return assemble_pdf(pages, title=title, created=created)


def test_the_pdf_has_a_page_per_encoded_page_in_order() -> None:
    s = scene()
    pages = [
        encode_page(colour_page(s), C),
        encode_page(grey_page(s), G),
        encode_page(bw_page(s), B),
    ]
    pdf = reader(make(pages))
    assert len(pdf.pages) == 3
    assert [image_object(pdf, i)["/ColorSpace"] for i in range(3)] == [
        "/DeviceRGB",
        "/DeviceGray",
        "/DeviceGray",
    ]


@pytest.mark.parametrize("dpi", [100, 150, 300])
def test_a_page_is_as_big_as_its_pixels_at_its_resolution(dpi: int) -> None:
    encoded = encode_page(colour_page(scene(dpi)), C)
    pdf = reader(make([encoded]))
    width, height = page_size_pt(pdf, 0)
    assert width == pytest.approx(expected_points(encoded.width, dpi), abs=0.2)
    assert height == pytest.approx(expected_points(encoded.height, dpi), abs=0.2)
    assert width == pytest.approx(612.0, abs=0.5)  # Letter
    assert height == pytest.approx(792.0, abs=0.5)


def test_pages_of_different_resolutions_each_get_their_own_size() -> None:
    low, high = encode_page(colour_page(scene(100)), C), encode_page(colour_page(scene(150)), C)
    pdf = reader(make([low, high]))
    assert page_size_pt(pdf, 0) == pytest.approx(page_size_pt(pdf, 1), abs=0.5)  # both Letter


def test_colour_and_grey_pages_embed_the_jpeg_without_re_encoding() -> None:
    s = scene()
    encoded = [encode_page(colour_page(s), C), encode_page(grey_page(s), G)]
    pdf = reader(make(encoded))
    for index, page in enumerate(encoded):
        image = image_object(pdf, index)
        assert image["/Filter"] == "/DCTDecode"
        assert image.get_data() == page.data


def test_black_and_white_embeds_lossless_one_bit_ccitt_g4() -> None:
    page = bw_page(scene())
    pdf = reader(make([encode_page(page, B)]))
    image = image_object(pdf, 0)
    assert image["/Filter"] == ["/CCITTFaxDecode"]
    assert image["/BitsPerComponent"] == 1
    assert np.array_equal(pdf_pixels(pdf, 0) > 127, page.pixels == 255)


def test_metadata_has_title_creation_date_and_producer() -> None:
    encoded = encode_page(colour_page(scene()), C)
    info = reader(make([encoded], title="Tax Return")).metadata
    assert info.title == "Tax Return"
    assert info.producer == PRODUCER == "fastfoto-linux"
    assert info.creation_date == FIXED_TIME
    assert info.modification_date == FIXED_TIME


def test_the_creation_date_follows_the_time_it_is_given() -> None:
    created = datetime(2020, 2, 29, 23, 59, 58, tzinfo=UTC)
    encoded = encode_page(colour_page(scene()), C)
    assert reader(make([encoded], created=created)).metadata.creation_date == created


def test_no_pages_is_an_error_not_an_empty_pdf() -> None:
    with pytest.raises(DocumentError, match="no pages"):
        make([])


def test_a_page_is_not_changed_by_being_assembled() -> None:
    encoded = encode_page(colour_page(scene()), C)
    copy = EncodedPage(encoded.data, encoded.mode, encoded.width, encoded.height, encoded.dpi)
    make([encoded])
    assert encoded == copy
