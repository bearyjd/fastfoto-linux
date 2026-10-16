"""The scan page while the scanner is checked before a scan: its text, Cancel, and failure."""

from pathlib import Path

import pytest

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.report import progress_text
from fastfoto_linux.gui.state import State
from fastfoto_linux.scanner import ScannerInUseError, ScannerStuckError
from fastfoto_linux.session import RawReason, SessionResult, Stage
from tests.gui.test_controller import Page

CHECKING = "Checking the scanner…"


@pytest.fixture
def page(out: Path) -> Page:
    return Page(ScanForm(output_folder=str(out)), [])


def test_the_page_says_the_scanner_is_being_checked(page: Page) -> None:
    controller = page.scanning()
    changes = page.changes

    controller.on_stage(Stage.CHECKING)

    assert controller.state is State.SCANNING
    assert controller.progress_text == CHECKING
    assert page.changes > changes  # the window is told


def test_the_text_goes_back_to_scanning_when_the_scan_begins(page: Page) -> None:
    controller = page.scanning()
    controller.on_stage(Stage.CHECKING)

    controller.on_stage(Stage.SCANNING)

    assert controller.progress_text == "Scanning page 1"


def test_a_finished_page_ends_the_checking_text_too(page: Page) -> None:
    controller = page.scanning()
    controller.on_stage(Stage.CHECKING)

    controller.on_page(1)

    assert controller.progress_text == "Scanning page 2"


def test_cancel_during_the_check_shows_cancelling_at_once(page: Page) -> None:
    controller = page.scanning()
    controller.on_stage(Stage.CHECKING)
    assert controller.can_cancel

    controller.cancel()

    assert controller.state is State.CANCELLING
    assert controller.progress_text == "Cancelling…"
    assert page.worker.names[-1] == "cancel"


def test_a_late_checking_stage_does_not_change_the_cancelling_text(page: Page) -> None:
    controller = page.scanning()
    controller.cancel()

    controller.on_stage(Stage.CHECKING)

    assert controller.progress_text == "Cancelling…"


@pytest.mark.parametrize("error", [ScannerStuckError(), ScannerInUseError()], ids=["stuck", "busy"])
def test_a_scanner_that_failed_the_check_is_reported_in_its_own_words(
    page: Page, error: Exception
) -> None:
    controller = page.scanning()
    controller.on_stage(Stage.CHECKING)

    controller.on_finished(
        SessionResult(error=error, raw_reason=RawReason.SCAN_ERROR, raw_dir=None)
    )

    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert str(error) in controller.banner.text
    assert controller.progress_text == ""


def test_a_cancel_during_the_check_ends_as_a_normal_cancel(page: Page) -> None:
    controller = page.scanning()
    controller.on_stage(Stage.CHECKING)
    controller.cancel()

    controller.on_finished(SessionResult(cancelled=True))

    assert controller.state is State.CANCELLED
    assert controller.banner is not None
    assert controller.banner.text == "Cancelled. Nothing was scanned."


def test_the_next_scan_does_not_start_with_the_old_checking_text(page: Page) -> None:
    controller = page.scanning()
    controller.on_stage(Stage.CHECKING)
    controller.on_finished(SessionResult(error=ScannerStuckError()))

    controller.start_scan()

    assert controller.progress_text == "Scanning page 1"


def test_the_report_has_the_checking_text_only_for_the_scanning_state() -> None:
    assert progress_text(State.SCANNING, 0, 0, checking=True) == CHECKING
    assert progress_text(State.SCANNING, 0, 0) == "Scanning page 1"
    assert progress_text(State.PROCESSING, 0, 0, checking=True) == "Processing photo 1"
    assert progress_text(State.CANCELLING, 0, 0, checking=True) == "Cancelling…"


def test_a_slow_scanner_keeps_the_checking_text_and_the_state(page: Page) -> None:
    controller = page.scanning()
    controller.on_stage(Stage.CHECKING)

    controller.on_stage(Stage.WAITING)

    assert controller.state is State.SCANNING
    assert controller.progress_text == CHECKING
