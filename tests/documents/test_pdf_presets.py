"""The PDF a preset produces: filters, lossless pixels, page size held, B/W untouched."""

import io
from datetime import UTC, datetime

import numpy as np
import pikepdf
import pytest
from pikepdf import PdfImage

from fastfoto_linux.documents.encode import EncodedPage, encode_page
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.pdf import assemble_pdf
from fastfoto_linux.output.presets import ExportPreset
from tests.documents.test_encode_presets import ALL, colour, grey, grey_pixels

POINT_TOLERANCE = 0.5
CREATED = datetime(2026, 1, 2, tzinfo=UTC)


def open_pdf(pages: list[EncodedPage]) -> pikepdf.Pdf:
    return pikepdf.open(io.BytesIO(assemble_pdf(pages, title="t", created=CREATED)))


def image_of(pdf: pikepdf.Pdf) -> pikepdf.Object:
    return next(iter(pdf.pages[0].get_images().values()))


def filter_of(pdf: pikepdf.Pdf) -> str:
    value = image_of(pdf).Filter
    return str(value[0] if isinstance(value, pikepdf.Array) else value)


def mediabox(pdf: pikepdf.Pdf) -> tuple[float, float]:
    box = pdf.pages[0].mediabox
    return float(box[2]) - float(box[0]), float(box[3]) - float(box[1])


def test_lossless_is_flate_and_pixel_exact() -> None:
    page = colour(300)

    pdf = open_pdf([encode_page(page, ColourMode.COLOUR, preset=ExportPreset.LOSSLESS)])

    assert filter_of(pdf) == "/FlateDecode"
    assert np.array_equal(np.asarray(PdfImage(image_of(pdf)).as_pil_image()), page.pixels)


def test_small_is_dct_a_third_wide_and_the_same_page_size() -> None:
    page = grey(600)
    plain = open_pdf([encode_page(page, ColourMode.GREY)])

    small = open_pdf([encode_page(page, ColourMode.GREY, preset=ExportPreset.SMALL)])

    assert filter_of(small) == "/DCTDecode"
    assert int(image_of(small).Width) * 3 == int(image_of(plain).Width)
    for ours, theirs in zip(mediabox(small), mediabox(plain), strict=True):
        assert abs(ours - theirs) <= POINT_TOLERANCE


@pytest.mark.parametrize("preset", ALL, ids=str)
def test_black_and_white_stays_ccitt(preset: ExportPreset | None) -> None:
    pixels = np.where(grey_pixels(240, 600) > 100, 255, 0).astype(np.uint8)

    pdf = open_pdf(
        [encode_page(LoadedPage(pixels, ColourMode.BW, 600), ColourMode.BW, preset=preset)]
    )

    assert filter_of(pdf) == "/CCITTFaxDecode"
