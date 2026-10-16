"""A page that passes the load check but would trim to under 10 mm is kept untrimmed.

Trimming it would leave a page that ``find_marks`` refuses, and one such page must not stop a
run that has other pages to write.
"""

import logging
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents import DocumentSettings, OcrMode, build_document
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import LETTER_MM, Scene, paper_scene, with_text
from tests.documents.helpers import DPI, colour_page, grey_page, reader, write_pages

PAPER_MM = (LETTER_MM[0], 5.0)  # a strip of paper: 5 mm tall
FRAME_MM = (LETTER_MM[0], 12.0)  # on a frame just over the 10 mm a page must measure
MIN_PAGE_MM = 10.0


def strip_scene() -> Scene:
    """5 mm of paper with one mark in it, then white: trimmed, it would be 8 to 9 mm tall."""
    return with_text(paper_scene(dpi=DPI, paper_mm=PAPER_MM, scan_mm=FRAME_MM), 25.0, 1.0, 10)


@pytest.mark.parametrize("make", [colour_page, grey_page], ids=["colour", "grey"])
def test_a_page_that_would_trim_to_under_10_mm_is_kept_whole(make, caplog) -> None:
    page = make(strip_scene())
    with caplog.at_level(logging.DEBUG, logger="fastfoto_linux.documents.trim"):
        result = trim_page(page)
    assert (result.left, result.right, result.bottom) == (0, 0, 0)
    assert result.page.pixels.shape == page.pixels.shape
    assert any(record.levelno == logging.DEBUG for record in caplog.records)


def test_such_a_page_does_not_stop_the_run(tmp_path: Path) -> None:
    pages = write_pages(tmp_path / "raw", [strip_scene()])
    out = tmp_path / "out"
    out.mkdir()
    settings = replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), keep_blank=True)
    result = build_document(pages, settings)
    pdf = reader(result.pdf.read_bytes())
    assert len(pdf.pages) == 1
    assert float(pdf.pages[0].mediabox.height) * 25.4 / 72 >= MIN_PAGE_MM
