from pathlib import Path

import pytest

from fastfoto_linux.gui.report import error_text, progress_text, raw_reason_text, result_banner
from fastfoto_linux.gui.state import State
from fastfoto_linux.pipeline.process import ProcessResult, SheetIssue
from fastfoto_linux.scanner import ScanError, ScannerNotFoundError, ShimMissingError
from fastfoto_linux.session import RawReason, SessionResult
from tests.gui.helpers import cancelled_scan, clean_result, written

RAW = Path("/srv/demo/FastFoto/.raw/20261013T230000Z")
OUT = Path("/srv/demo/FastFoto")


def test_every_raw_reason_has_its_own_sentence() -> None:
    texts = {reason: raw_reason_text(reason) for reason in RawReason}
    assert all(texts.values())
    assert len(set(texts.values())) == len(RawReason)


def test_scanner_problems_say_what_to_do() -> None:
    assert "check the cable" in error_text(
        ScannerNotFoundError("no FF-680W found on USB; check the cable and the power switch")
    )
    assert "make -C tools/usb-gap-shim" in error_text(
        ShimMissingError("the shim is missing; build it with `make -C tools/usb-gap-shim`")
    )


def test_other_errors_name_their_kind_and_message() -> None:
    assert error_text(RuntimeError("boom")) == "RuntimeError: boom"
    assert error_text(OSError(28, "No space left on device", "/srv/demo")) == (
        "No space left on device: /srv/demo"
    )


@pytest.mark.parametrize(
    ("state", "pages", "photos", "expected"),
    [
        (State.CHECKING, 0, 0, "Looking for the scanner…"),
        (State.SCANNING, 0, 0, "Scanning page 1"),
        (State.SCANNING, 4, 0, "Scanning page 5"),
        (State.PROCESSING, 6, 0, "Processing photo 1"),
        (State.PROCESSING, 6, 3, "Processing photo 4"),
        (State.CANCELLING, 6, 3, "Cancelling…"),
        (State.READY, 6, 3, ""),
        (State.DONE, 6, 3, ""),
    ],
)
def test_progress_counts_the_page_or_photo_being_worked_on(
    state: State, pages: int, photos: int, expected: str
) -> None:
    assert progress_text(state, pages, photos) == expected


def test_a_cancel_during_the_scan_offers_the_pages_kept() -> None:
    banner = result_banner(State.CANCELLED, cancelled_scan(RAW, pages=3))
    assert banner is not None
    assert banner.kind == "info"
    assert banner.text == f"3 pages were scanned before you cancelled — kept in {RAW}"


def test_one_kept_page_is_singular() -> None:
    banner = result_banner(State.CANCELLED, cancelled_scan(RAW, pages=1))
    assert banner is not None
    assert banner.text.startswith("1 page was scanned before you cancelled")


def test_a_cancel_during_processing_says_how_many_photos_were_saved() -> None:
    result = SessionResult(
        process=ProcessResult(written=(written(OUT, 1), written(OUT, 2)), cancelled=True),
        pages_scanned=6,
        raw_dir=RAW,
        raw_reason=RawReason.CANCELLED,
        cancelled=True,
        kept_pages=(RAW / "page-0001.png",),
    )
    banner = result_banner(State.CANCELLED, result)
    assert banner is not None
    assert "2 photos were saved" in banner.text
    assert str(RAW) in banner.text


def test_a_cancel_before_anything_was_scanned_says_so() -> None:
    banner = result_banner(State.CANCELLED, SessionResult(cancelled=True))
    assert banner is not None
    assert "Nothing was scanned" in banner.text


def test_a_failure_says_what_went_wrong_and_where_the_raw_pages_are() -> None:
    result = SessionResult(
        error=ScanError("scanimage timed out"),
        pages_scanned=0,
        raw_dir=RAW,
        raw_reason=RawReason.SCAN_ERROR,
    )
    banner = result_banner(State.FAILED, result)
    assert banner is not None
    assert banner.kind == "error"
    assert "scanimage timed out" in banner.text
    assert str(RAW) in banner.text
    assert raw_reason_text(RawReason.SCAN_ERROR) in banner.text


def test_a_failure_without_raw_pages_does_not_mention_them() -> None:
    banner = result_banner(State.FAILED, SessionResult(error=OSError("no space")))
    assert banner is not None
    assert "raw" not in banner.text.lower()


def test_a_clean_run_reports_the_photos_saved() -> None:
    banner = result_banner(State.DONE, clean_result(OUT / "Family Trips", photos=3))
    assert banner is not None
    assert banner.kind == "positive"
    assert "3 photos saved" in banner.text
    assert str(OUT / "Family Trips") in banner.text


def test_one_photo_is_singular() -> None:
    banner = result_banner(State.DONE, clean_result(OUT, photos=1))
    assert banner is not None
    assert "1 photo saved" in banner.text


def test_a_run_that_found_no_photos_is_a_warning() -> None:
    banner = result_banner(State.DONE, SessionResult(process=ProcessResult(), pages_scanned=2))
    assert banner is not None
    assert banner.kind == "warning"
    assert "No photos" in banner.text


def test_sheets_that_could_not_be_processed_are_a_warning_with_the_raw_pages() -> None:
    process = ProcessResult(
        written=(written(OUT, 1),),
        failed=(SheetIssue(sheet=2, pages=("page-0003.png",), reason="no photo found"),),
    )
    result = SessionResult(
        process=process, pages_scanned=4, raw_dir=RAW, raw_reason=RawReason.SHEETS_FAILED
    )
    banner = result_banner(State.DONE, result)
    assert banner is not None
    assert banner.kind == "warning"
    assert "1 sheet could not be processed" in banner.text
    assert str(RAW) in banner.text


def test_raw_pages_kept_after_a_clean_run_are_mentioned_calmly() -> None:
    result = SessionResult(
        process=ProcessResult(written=(written(OUT, 1),)),
        pages_scanned=2,
        raw_dir=RAW,
        raw_reason=RawReason.BACK_DROPPED,
    )
    banner = result_banner(State.DONE, result)
    assert banner is not None
    assert banner.kind == "positive"
    assert str(RAW) in banner.text


@pytest.mark.parametrize("state", [State.IDLE, State.READY, State.SCANNING])
def test_there_is_nothing_to_say_before_a_session_has_ended(state: State) -> None:
    assert result_banner(state, SessionResult()) is None
