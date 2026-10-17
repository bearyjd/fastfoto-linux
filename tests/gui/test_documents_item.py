"""A PDF as the results list shows it: name, pages, blank pages left out, searchable text."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import OcrStatus
from fastfoto_linux.gui.documents import DocumentItem, item_from_document
from tests.gui.doc_helpers import document


def item(out: Path, **options: object) -> DocumentItem:
    return item_from_document(document(out, **options))


def test_the_item_has_the_file_its_folder_and_its_pages(tmp_path: Path) -> None:
    made = item(tmp_path, pages=3, dropped=(2, 4))
    assert made.pdf == tmp_path / "Document_0001.pdf"
    assert made.file_name == "Document_0001.pdf"
    assert made.folder == tmp_path
    assert made.pages == 3  # the pages in the PDF, not the pages scanned


@pytest.mark.parametrize(("pages", "text"), [(1, "1 page"), (2, "2 pages"), (12, "12 pages")])
def test_the_page_count_reads_as_a_sentence_would(tmp_path: Path, pages: int, text: str) -> None:
    assert item(tmp_path, pages=pages).pages_text == text


@pytest.mark.parametrize(
    ("dropped", "text"),
    [
        ((), ""),
        ((2,), "Blank page left out: 2"),
        ((2, 4), "Blank pages left out: 2, 4"),
    ],
)
def test_blank_pages_are_listed_by_number(
    tmp_path: Path, dropped: tuple[int, ...], text: str
) -> None:
    assert item(tmp_path, dropped=dropped).dropped_text == text


@pytest.mark.parametrize(
    ("status", "detail", "text", "warning"),
    [
        (OcrStatus.DONE, "", "Searchable text: yes", False),
        (OcrStatus.SKIPPED, "", "Searchable text: no (turned off)", False),
        (OcrStatus.UNAVAILABLE, "x", "Searchable text: no (OCRmyPDF is not installed)", False),
        (
            OcrStatus.FAILED,
            "ocrmypdf exited with 6",
            "Searchable text could not be added (ocrmypdf exited with 6); "
            "the plain PDF was saved instead",
            True,
        ),
        (
            OcrStatus.TIMED_OUT,
            "",
            "Searchable text could not be added (timed out); the plain PDF was saved instead",
            True,
        ),
    ],
)
def test_the_searchable_text_line_says_what_happened(
    tmp_path: Path, status: OcrStatus, detail: str, text: str, warning: bool
) -> None:
    made = item(tmp_path, ocr=status, detail=detail)
    assert made.searchable_text == text
    assert made.ocr_warning is warning


def test_an_item_is_a_value(tmp_path: Path) -> None:
    assert item(tmp_path) == item(tmp_path)
    assert item(tmp_path) != item(tmp_path, pages=4)
