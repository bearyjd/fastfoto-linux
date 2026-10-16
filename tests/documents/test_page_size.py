"""A page smaller than 10 mm each way is refused with a clear message, not a raw OpenCV error."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.documents import (
    DocumentSettings,
    OcrMode,
    UnsupportedPageError,
    build_document,
)
from fastfoto_linux.documents.blank import is_blank
from fastfoto_linux.documents.loader import LoadedPage, inspect_page, load_page
from fastfoto_linux.documents.marks import find_marks
from fastfoto_linux.documents.modes import ColourMode
from tests.doc_synth import write_png

DPI = 100  # 10 mm are 39 pixels at this resolution


def grey_png(path: Path, height: int, width: int, *, dpi: int = DPI) -> Path:
    return write_png(path, np.full((height, width), 240, np.uint8), dpi=dpi)


@pytest.mark.parametrize("shape", [(1, 1), (30, 200), (200, 30), (38, 38)], ids=str)
def test_a_page_under_10_mm_each_way_is_refused_by_name(tmp_path: Path, shape) -> None:
    path = grey_png(tmp_path / "stamp.png", *shape)
    with pytest.raises(UnsupportedPageError, match=r"stamp\.png.*mm"):
        inspect_page(path)
    with pytest.raises(UnsupportedPageError, match=r"stamp\.png.*mm"):
        load_page(path)


def test_the_smallest_accepted_page_is_10_mm_each_way(tmp_path: Path) -> None:
    path = grey_png(tmp_path / "small.png", 40, 40)
    assert inspect_page(path).width == 40
    assert load_page(path).pixels.shape == (40, 40)


def test_the_size_is_judged_with_the_resolution_the_page_ends_up_with(tmp_path: Path) -> None:
    path = write_png(tmp_path / "bare.png", np.full((60, 60), 240, np.uint8), dpi=None)
    assert inspect_page(path, fallback_dpi=100).dpi == 100  # 15 mm
    with pytest.raises(UnsupportedPageError, match=r"bare\.png.*mm"):
        inspect_page(path, fallback_dpi=300)  # 5 mm


@pytest.mark.parametrize("shape", [(1, 1), (1, 300), (300, 1), (5, 5)], ids=str)
def test_analysing_a_tiny_page_raises_a_documents_error_never_a_raw_one(shape) -> None:
    page = LoadedPage(np.full(shape, 240, np.uint8), ColourMode.GREY, 300)
    with pytest.raises(UnsupportedPageError, match="mm"):
        find_marks(page)
    with pytest.raises(UnsupportedPageError, match="mm"):
        is_blank(page)


def test_a_tiny_page_stops_the_run_before_anything_is_written(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    out.mkdir()
    pages = [grey_png(raw / "page-01.png", 400, 300), grey_png(raw / "page-02.png", 1, 1, dpi=300)]
    settings = replace(DocumentSettings(output_root=out), ocr=OcrMode.OFF)
    with pytest.raises(UnsupportedPageError, match=r"page-02\.png.*mm"):
        build_document(pages, settings)
    assert not [p for p in out.iterdir() if not p.name.startswith(".")]
