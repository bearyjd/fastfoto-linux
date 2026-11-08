"""Document pages are decoded with the loader's rules, from bytes, naming no file."""

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents.errors import UnsupportedPageError
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.evaluation import calib_pages
from fastfoto_linux.evaluation.calib_detail import Strengths
from tests.calibration.synth import bilevel_png, colour_png, png


def test_kinds_and_resolution_are_read_from_the_png() -> None:
    page = calib_pages.decode_page(colour_png("text"), None)
    assert (page.kind, page.dpi, page.pixels.ndim) == (ColourMode.COLOUR, 100, 3)
    grey = calib_pages.decode_page(png(np.full((400, 400), 200, np.uint8), dpi=120), None)
    assert (grey.kind, grey.dpi) == (ColourMode.GREY, 120)
    bilevel = calib_pages.decode_page(bilevel_png(), None)
    assert bilevel.kind is ColourMode.BW and set(np.unique(bilevel.pixels)) <= {0, 255}


def test_the_annotation_dpi_is_only_a_fallback() -> None:
    plain = png(np.full((400, 400), 200, np.uint8))
    assert calib_pages.decode_page(plain, 150).dpi == 150
    assert calib_pages.decode_page(png(np.full((400, 400), 200, np.uint8), dpi=120), 150).dpi == 120
    with pytest.raises(ValueError, match="resolution"):
        calib_pages.decode_page(plain, None)


@pytest.mark.parametrize(
    "data",
    [
        png(np.full((20, 20), 200, np.uint8), dpi=100),  # under 10 mm each way
        png(np.full((400, 400, 4), 200, np.uint8), dpi=100),  # alpha
        png(np.full((400, 400), 200, np.uint8), dpi=40),  # absurd resolution
        b"not a png",
    ],
)
def test_pages_the_document_tools_would_refuse_are_refused(data: bytes) -> None:
    with pytest.raises((ValueError, OSError, UnsupportedPageError, Image.UnidentifiedImageError)):
        calib_pages.decode_page(data, None)


def test_a_page_over_the_pixel_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calib_pages, "MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="pixel cap"):
        calib_pages.decode_page(colour_png("text"), None)


@pytest.mark.parametrize("bad", [(-1, 0, 0), (0, 101, 0), (0, 0, True), (0, 0, 50.0)])
def test_strengths_are_whole_numbers_from_zero_to_one_hundred(bad) -> None:
    with pytest.raises(ValueError, match="strength"):
        Strengths(*bad)
