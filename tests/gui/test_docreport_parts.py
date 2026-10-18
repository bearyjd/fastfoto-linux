"""A document of several PDFs in the results list and the banner."""

from pathlib import Path

from fastfoto_linux.documents import DocumentResult, OcrOutcome, OcrStatus, PartResult
from fastfoto_linux.gui.docreport import document_result_banner
from fastfoto_linux.gui.documents import item_from_document, items_from_document
from fastfoto_linux.gui.state import State
from fastfoto_linux.session import DocumentSessionResult

OUT = Path("/out")


def _part(name: str, pages: int, status: OcrStatus = OcrStatus.DONE) -> PartResult:
    return PartResult(OUT / f"{name}_0001.pdf", name, pages, OcrOutcome(status))


def _result(*parts: PartResult, dropped: tuple[int, ...] = (), removed: tuple[int, ...] = ()):
    return DocumentResult(
        pages_read=sum(p.pages for p in parts) + len(dropped) + len(removed),
        dropped=dropped,
        parts=parts,
        removed=removed,
    )


def _banner(result: DocumentResult):
    session = DocumentSessionResult(document=result, pages_scanned=result.pages_read)
    return document_result_banner(State.DONE, session)


def test_a_one_part_result_is_one_item_as_before() -> None:
    result = _result(_part("Document", 3), dropped=(2,))
    (item,) = items_from_document(result)
    assert item == item_from_document(result)
    assert (item.file_name, item.pages, item.dropped) == ("Document_0001.pdf", 3, (2,))


def test_each_part_is_an_item_and_the_left_out_pages_are_told_once() -> None:
    result = _result(_part("Tax", 2), _part("Receipts", 3), dropped=(4,), removed=(6,))
    first, second = items_from_document(result)
    assert (first.file_name, first.pages, first.dropped) == ("Tax_0001.pdf", 2, (4,))
    assert (second.file_name, second.pages, second.dropped) == ("Receipts_0001.pdf", 3, ())
    assert first.removed_text == "Pages you removed: 6"
    assert second.removed_text == ""


def test_the_banner_names_every_pdf() -> None:
    banner = _banner(_result(_part("Tax", 2), _part("Receipts", 3)))
    assert banner is not None
    assert banner.kind == "positive"
    for words in ("2 PDFs", "Tax_0001.pdf", "Receipts_0001.pdf", "2 pages", "3 pages", str(OUT)):
        assert words in banner.text


def test_one_part_with_a_removed_page_says_so() -> None:
    banner = _banner(_result(_part("Document", 3), removed=(2,)))
    assert banner is not None
    assert "Document_0001.pdf" in banner.text
    assert "Pages you removed: 2" in banner.text


def test_a_problem_with_the_text_of_any_part_is_a_warning() -> None:
    banner = _banner(_result(_part("Tax", 2), _part("Receipts", 3, OcrStatus.FAILED)))
    assert banner is not None
    assert banner.kind == "warning"
