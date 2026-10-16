"""The words of Documents mode: progress, results, failures, the offer to process kept pages."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import (
    AllPagesBlankError,
    DocumentSettingsError,
    OcrMissingError,
    OcrStatus,
    UnsupportedPageError,
)
from fastfoto_linux.gui.docreport import (
    document_error_banner,
    document_kept_text,
    document_progress_text,
    document_result_banner,
    offers_kept,
)
from fastfoto_linux.gui.state import State
from fastfoto_linux.scanner import NoDocumentsError, ScanError
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult
from tests.gui.doc_helpers import cancelled_document, clean_document, stopped_document

RAW = Path("/raw/.raw/stamp")

# -- progress --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "pages", "options", "text"),
    [
        (State.CHECKING, 0, {}, "Looking for the scanner…"),
        (State.SCANNING, 0, {"checking": True}, "Checking the scanner…"),
        (State.SCANNING, 0, {}, "Scanning page 1"),
        (State.SCANNING, 4, {}, "Scanning page 5"),
        (State.PROCESSING, 6, {}, "Making the PDF…"),
        (State.PROCESSING, 6, {"pdf_page": 2, "pdf_total": 6}, "Making the PDF (page 2 of 6)"),
        (
            State.PROCESSING,
            6,
            {"pdf_page": 6, "pdf_total": 6, "ocr": True},
            "Adding searchable text…",
        ),
        (State.CANCELLING, 3, {}, "Cancelling…"),
        (State.READY, 0, {}, ""),
        (State.DONE, 3, {}, ""),
    ],
)
def test_the_progress_line_follows_the_stage(
    state: State, pages: int, options: dict[str, object], text: str
) -> None:
    assert document_progress_text(state, pages, **options) == text


# -- a PDF was made --------------------------------------------------------------------------


def test_a_clean_run_says_where_the_pdf_is_and_how_long(tmp_path: Path) -> None:
    banner = document_result_banner(State.DONE, clean_document(tmp_path, pages=3))
    assert banner is not None
    assert banner.kind == "positive"
    assert banner.text == f"Document_0001.pdf saved to {tmp_path}: 3 pages."


def test_one_page_is_one_page(tmp_path: Path) -> None:
    banner = document_result_banner(State.DONE, clean_document(tmp_path, pages=1))
    assert banner is not None
    assert banner.text.endswith(": 1 page.")


def test_dropped_blank_pages_are_named_by_number(tmp_path: Path) -> None:
    result = clean_document(tmp_path, pages=2, dropped=(2, 4))
    banner = document_result_banner(State.DONE, result)
    assert banner is not None
    assert "Blank pages left out: 2, 4." in banner.text


def test_kept_raw_pages_are_said_to_be_kept_and_why(tmp_path: Path) -> None:
    made = clean_document(tmp_path, dropped=(2,))
    result = DocumentSessionResult(
        document=made.document,
        pages_scanned=4,
        raw_dir=RAW,
        raw_reason=DocumentRawReason.PAGES_DROPPED,
    )
    banner = document_result_banner(State.DONE, result)
    assert banner is not None
    assert banner.text.endswith(f" Raw pages kept in {RAW} (blank pages were left out).")


def test_a_pdf_without_its_searchable_text_is_a_warning_in_the_cli_words(tmp_path: Path) -> None:
    made = clean_document(tmp_path, ocr=OcrStatus.FAILED, detail="ocrmypdf exited with 6")
    result = DocumentSessionResult(
        document=made.document,
        pages_scanned=3,
        raw_dir=RAW,
        raw_reason=DocumentRawReason.OCR_FAILED,
    )
    banner = document_result_banner(State.DONE, result)
    assert banner is not None
    assert banner.kind == "warning"
    assert banner.text.startswith(f"Document_0001.pdf saved to {tmp_path}, but searchable text")
    assert "could not be added (ocrmypdf exited with 6)" in banner.text
    assert "the plain PDF was saved instead" in banner.text
    assert f"Raw pages kept in {RAW} (searchable text could not be added)" in banner.text


# -- cancelled -------------------------------------------------------------------------------


def test_a_cancel_that_kept_pages_offers_them(tmp_path: Path) -> None:
    banner = document_result_banner(State.CANCELLED, cancelled_document(RAW, 3))
    assert banner is not None
    assert banner.kind == "info"
    assert banner.text == f"3 pages were scanned before you cancelled — kept in {RAW}"


def test_a_cancel_before_any_page_says_nothing_was_scanned() -> None:
    banner = document_result_banner(State.CANCELLED, DocumentSessionResult(cancelled=True))
    assert banner is not None
    assert banner.text == "Cancelled. Nothing was scanned."


# -- failures, in plain words ----------------------------------------------------------------


def test_a_scanner_that_failed_part_way_says_no_pdf_was_made_from_part_of_a_stack() -> None:
    result = stopped_document(RAW, ScanError("the paper jammed"), pages=2)
    banner = document_result_banner(State.FAILED, result)
    assert banner is not None
    assert banner.kind == "error"
    assert banner.text.startswith("The scan failed. the paper jammed.")
    assert f"Raw pages kept in {RAW} (the scanner reported an error)." in banner.text


def test_an_empty_feeder_is_said_for_documents() -> None:
    banner = document_error_banner(NoDocumentsError("no paper"))
    assert banner.kind == "error"
    assert banner.text == (
        "The scan failed. The feeder is empty. Load the pages in the feeder and press Scan."
    )


@pytest.mark.parametrize(
    "error",
    [DocumentSettingsError("the name '///' has no usable characters"), OcrMissingError("x")],
)
def test_a_refusal_before_the_scan_says_the_scan_did_not_start(error: Exception) -> None:
    banner = document_error_banner(error)
    assert banner.kind == "error"
    assert banner.text == f"The scan did not start: {error}."


def test_all_pages_blank_says_no_pdf_was_made_and_where_the_pages_are() -> None:
    error = AllPagesBlankError("all 3 pages look blank, so no PDF was written")
    banner = document_error_banner(error, RAW, DocumentRawReason.ERROR)
    assert banner.text == (
        "No PDF was made. all 3 pages look blank, so no PDF was written."
        f" Raw pages kept in {RAW} (something went wrong)."
    )


def test_an_unusable_page_is_a_no_pdf_message_too() -> None:
    banner = document_error_banner(UnsupportedPageError("page-0002.png is not a PNG"))
    assert banner.text.startswith("No PDF was made. page-0002.png is not a PNG.")


def test_other_errors_are_named_for_what_they_are() -> None:
    banner = document_error_banner(OSError(28, "No space left on device", "/out"))
    assert banner.text == "The scan failed. No space left on device: /out."


# -- the offer to process the kept pages -----------------------------------------------------


def test_pages_kept_by_a_cancel_are_offered() -> None:
    assert offers_kept(cancelled_document(RAW)) is True


def test_pages_kept_by_a_scanner_that_stopped_are_offered() -> None:
    assert offers_kept(stopped_document(RAW, ScanError("jam"))) is True


def test_pages_that_failed_to_make_a_pdf_are_not_offered_again() -> None:
    again = DocumentSessionResult(
        error=AllPagesBlankError("blank"),
        raw_dir=RAW,
        raw_reason=DocumentRawReason.ERROR,
        kept_pages=cancelled_document(RAW).kept_pages,
    )
    assert offers_kept(again) is False


def test_a_finished_pdf_or_no_kept_pages_is_no_offer(tmp_path: Path) -> None:
    assert offers_kept(clean_document(tmp_path)) is False
    assert offers_kept(DocumentSessionResult(cancelled=True)) is False


def test_the_offer_for_a_cancel_counts_the_pages() -> None:
    assert document_kept_text(cancelled_document(RAW, 1)) == (
        f"1 page was scanned before you cancelled — kept in {RAW}"
    )
    assert document_kept_text(cancelled_document(RAW, 4)) == (
        f"4 pages were scanned before you cancelled — kept in {RAW}"
    )


def test_the_offer_for_a_scanner_that_stopped_says_why_there_is_no_pdf() -> None:
    text = document_kept_text(stopped_document(RAW, ScanError("jam"), pages=2))
    assert text == (
        f"The scanner stopped after 2 pages — kept in {RAW}. No PDF is made from part of a stack."
    )
