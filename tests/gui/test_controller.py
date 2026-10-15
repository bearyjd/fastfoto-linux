import logging
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.state import InvalidTransitionError, State
from fastfoto_linux.pipeline.process import ProcessResult
from fastfoto_linux.scanner import ScanError, ScannerNotFoundError
from fastfoto_linux.session import RawReason, SessionResult, Stage
from tests.gui.helpers import FakeWorker, cancelled_scan, clean_result, written


class Page:
    """A controller with a fake worker, counting the changes it announces."""

    def __init__(self, form: ScanForm, saved: list[ScanForm]) -> None:
        self.worker = FakeWorker()
        self.kept = SessionResult()
        self.changes = 0
        self.controller = Controller(
            self.worker, form, save_form=saved.append, on_change=self._changed
        )

    def _changed(self) -> None:
        self.changes += 1

    def ready(self) -> Controller:
        self.controller.check_scanner()
        self.controller.on_scanner(None)
        return self.controller

    def scanning(self) -> Controller:
        controller = self.ready()
        controller.start_scan()
        return controller

    def processing(self) -> Controller:
        controller = self.scanning()
        controller.on_stage(Stage.PROCESSING)
        return controller

    def cancelled(self, pages: int = 3) -> Controller:
        controller = self.scanning()
        controller.cancel()
        self.kept = cancelled_scan(Path("/srv/demo/.raw/stamp"), pages)
        controller.on_finished(self.kept)
        return controller


@pytest.fixture
def saved() -> list[ScanForm]:
    return []


@pytest.fixture
def page(out: Path, saved: list[ScanForm]) -> Page:
    return Page(ScanForm(output_folder=str(out)), saved)


def test_a_new_page_is_idle_with_the_forms_errors(saved: list[ScanForm]) -> None:
    controller = Page(ScanForm(), saved).controller
    assert controller.state is State.IDLE
    assert set(controller.errors) == {"output_folder"}
    assert not controller.can_scan
    assert controller.can_check
    assert not controller.can_cancel
    assert controller.banner is None


def test_checking_the_scanner(page: Page) -> None:
    controller = page.controller
    controller.check_scanner()
    assert controller.state is State.CHECKING
    assert controller.busy
    assert page.worker.names == ["check"]
    assert not controller.can_check
    controller.on_scanner(None)
    assert controller.state is State.READY
    assert "found" in controller.scanner_text.lower()
    assert controller.can_scan


def test_no_scanner_says_why_and_can_be_checked_again(page: Page) -> None:
    controller = page.controller
    controller.check_scanner()
    controller.on_scanner(ScannerNotFoundError("no FF-680W found on USB; check the cable"))
    assert controller.state is State.NO_SCANNER
    assert "check the cable" in controller.scanner_text
    assert not controller.can_scan
    assert controller.can_check
    controller.check_scanner()
    assert controller.state is State.CHECKING


def test_a_late_scanner_answer_is_ignored(page: Page) -> None:
    controller = page.scanning()
    controller.on_scanner(ScannerNotFoundError("late"))
    assert controller.state is State.SCANNING


@pytest.mark.parametrize("state", [State.IDLE, State.CHECKING, State.NO_SCANNER])
def test_scan_needs_a_scanner_that_was_found(
    saved: list[ScanForm], out: Path, state: State
) -> None:
    controller = Page(ScanForm(output_folder=str(out)), saved).controller
    if state is State.CHECKING:
        controller.check_scanner()
    elif state is State.NO_SCANNER:
        controller.check_scanner()
        controller.on_scanner(ScannerNotFoundError("none"))
    assert not controller.can_scan
    with pytest.raises(InvalidTransitionError):
        controller.start_scan()


def test_scan_needs_a_valid_form(page: Page) -> None:
    controller = page.ready()
    controller.set_field("date", "soon")
    assert not controller.can_scan
    assert "date" in controller.errors
    with pytest.raises(InvalidTransitionError, match="date"):
        controller.start_scan()
    assert page.worker.names == ["check"]
    controller.set_field("date", "1975")
    assert controller.can_scan


def test_starting_a_scan_saves_the_form_and_starts_the_worker(
    page: Page, saved: list[ScanForm]
) -> None:
    controller = page.ready()
    controller.set_field("album", "Rome")
    controller.start_scan()
    assert controller.state is State.SCANNING
    assert page.worker.calls[-1] == ("scan", controller.form)
    assert saved == [controller.form]
    assert controller.form.album == "Rome"
    assert controller.progress_text == "Scanning page 1"
    assert controller.can_cancel
    assert not controller.can_scan


def test_a_form_that_cannot_be_saved_does_not_stop_the_scan(
    out: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(form: ScanForm) -> None:
        raise OSError("read-only home")

    worker = FakeWorker()
    controller = Controller(worker, ScanForm(output_folder=str(out)), save_form=broken)
    controller.check_scanner()
    controller.on_scanner(None)
    with caplog.at_level(logging.WARNING):
        controller.start_scan()
    assert controller.state is State.SCANNING
    assert "read-only home" in caplog.text


def test_a_clean_run_goes_scanning_processing_done(page: Page, out: Path) -> None:
    controller = page.scanning()
    controller.on_stage(Stage.SCANNING)
    controller.on_page(1)
    controller.on_page(2)
    assert controller.progress_text == "Scanning page 3"
    controller.on_stage(Stage.PROCESSING)
    assert controller.state is State.PROCESSING
    assert controller.progress_text == "Processing photo 1"
    controller.on_photo(written(out, 1))
    controller.on_photo(written(out, 2, back=True))
    assert [item.index for item in controller.photos] == [1, 2]
    assert controller.photos[1].back is not None
    assert controller.progress_text == "Processing photo 3"
    controller.on_stage(Stage.DONE)
    assert controller.state is State.PROCESSING  # the result decides, not the stage
    controller.on_finished(clean_result(out, photos=2))
    assert controller.state is State.DONE
    assert controller.banner is not None
    assert controller.banner.kind == "positive"
    assert controller.progress_text == ""
    assert controller.can_scan
    assert not controller.busy


def test_the_results_folder_is_where_the_latest_photo_went(page: Page, out: Path) -> None:
    controller = page.processing()
    assert controller.results_folder is None
    controller.on_photo(written(out / "Rome", 1))
    assert controller.results_folder == out / "Rome"


def test_every_event_is_announced(page: Page, out: Path) -> None:
    controller = page.scanning()
    before = page.changes
    controller.on_page(1)
    controller.on_stage(Stage.PROCESSING)
    controller.on_photo(written(out, 1))
    controller.on_finished(clean_result(out, photos=1))
    assert page.changes >= before + 4


def test_a_new_scan_clears_the_previous_results(page: Page, out: Path) -> None:
    controller = page.processing()
    controller.on_photo(written(out, 1))
    controller.on_finished(clean_result(out, photos=1))
    assert len(controller.photos) == 1
    controller.start_scan()
    assert controller.photos == ()
    assert controller.banner is None


def test_cancel_asks_the_worker_and_waits_for_the_result(page: Page) -> None:
    controller = page.scanning()
    controller.cancel()
    assert controller.state is State.CANCELLING
    assert page.worker.names[-1] == "cancel"
    assert not controller.can_cancel
    assert controller.progress_text == "Cancelling…"
    with pytest.raises(InvalidTransitionError):
        controller.cancel()


def test_cancel_works_while_processing_too(page: Page) -> None:
    controller = page.processing()
    assert controller.can_cancel
    controller.cancel()
    assert controller.state is State.CANCELLING


@pytest.mark.parametrize("starter", ["ready", "idle"])
def test_cancel_when_nothing_runs_is_a_bug(page: Page, starter: str) -> None:
    controller = page.ready() if starter == "ready" else page.controller
    with pytest.raises(InvalidTransitionError):
        controller.cancel()


def test_a_cancelled_scan_offers_the_pages_kept(page: Page) -> None:
    controller = page.cancelled(pages=3)
    assert controller.state is State.CANCELLED
    assert controller.can_process_kept
    assert controller.banner is not None
    assert "3 pages were scanned before you cancelled" in controller.banner.text
    assert controller.can_scan


def test_a_cancel_that_came_too_late_leaves_a_complete_result(page: Page, out: Path) -> None:
    controller = page.scanning()
    controller.cancel()
    controller.on_finished(clean_result(out))
    assert controller.state is State.DONE
    assert not controller.can_process_kept


def test_processing_the_pages_kept(page: Page, out: Path) -> None:
    controller = page.cancelled(pages=3)
    kept = page.kept
    controller.process_kept()
    assert controller.state is State.PROCESSING
    assert page.worker.calls[-1] == ("process_kept", kept)
    assert not controller.can_process_kept
    assert controller.progress_text == "Processing photo 1"
    controller.on_photo(written(out, 1))
    controller.on_finished(
        SessionResult(
            process=ProcessResult(written=(written(out, 1),)),
            pages_scanned=3,
            raw_dir=kept.raw_dir,
            raw_reason=RawReason.CANCELLED,
        )
    )
    assert controller.state is State.DONE
    assert len(controller.photos) == 1
    assert not controller.can_process_kept


def test_processing_kept_pages_can_itself_be_cancelled(page: Page, out: Path) -> None:
    controller = page.cancelled()
    controller.process_kept()
    controller.cancel()
    result = SessionResult(
        process=ProcessResult(written=(written(out, 1),), cancelled=True),
        raw_dir=Path("/srv/demo/.raw/stamp"),
        raw_reason=RawReason.CANCELLED,
        cancelled=True,
    )
    controller.on_finished(result)
    assert controller.state is State.CANCELLED
    assert not controller.can_process_kept
    assert controller.banner is not None
    assert "1 photo was saved" in controller.banner.text


def test_process_kept_needs_kept_pages(page: Page) -> None:
    controller = page.ready()
    with pytest.raises(InvalidTransitionError):
        controller.process_kept()


def test_a_failed_session_shows_the_error_and_where_the_raw_pages_are(page: Page) -> None:
    controller = page.processing()
    controller.on_finished(
        SessionResult(
            error=RuntimeError("crash"),
            raw_dir=Path("/srv/demo/.raw/stamp"),
            raw_reason=RawReason.ERROR,
        )
    )
    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert controller.banner.kind == "error"
    assert "crash" in controller.banner.text
    assert "/srv/demo/.raw/stamp" in controller.banner.text


def test_a_scanner_error_needs_a_new_check_before_the_next_scan(page: Page) -> None:
    controller = page.scanning()
    controller.on_finished(
        SessionResult(error=ScanError("usb reset"), raw_dir=None, raw_reason=None)
    )
    assert controller.state is State.FAILED
    assert not controller.can_scan
    assert controller.can_check
    controller.check_scanner()
    controller.on_scanner(None)
    assert controller.can_scan


def test_other_failures_leave_the_scanner_usable(page: Page) -> None:
    controller = page.processing()
    controller.on_finished(SessionResult(error=RuntimeError("crash")))
    assert controller.can_scan


def test_an_error_from_the_worker_while_scanning_is_a_failure(page: Page) -> None:
    controller = page.scanning()
    controller.on_error(OSError(28, "No space left on device", "/srv/demo"))
    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert "No space left on device" in controller.banner.text


def test_a_scanner_that_vanished_by_scan_time_is_no_scanner(page: Page) -> None:
    controller = page.scanning()
    controller.on_error(ScannerNotFoundError("no FF-680W found on USB"))
    assert controller.state is State.NO_SCANNER
    assert "no FF-680W" in controller.scanner_text


def test_an_unexpected_error_while_checking_is_no_scanner(page: Page) -> None:
    controller = page.controller
    controller.check_scanner()
    controller.on_error(RuntimeError("sysfs exploded"))
    assert controller.state is State.NO_SCANNER
    assert "sysfs exploded" in controller.scanner_text


def test_an_error_while_processing_the_pages_kept_fails_the_page(page: Page) -> None:
    controller = page.cancelled()
    controller.process_kept()
    controller.on_error(RuntimeError("disk full"))
    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert "disk full" in controller.banner.text


def test_checking_again_is_not_possible_while_scanning(page: Page) -> None:
    controller = page.scanning()
    assert not controller.can_check
    with pytest.raises(InvalidTransitionError):
        controller.check_scanner()


@pytest.mark.parametrize("final", ["done", "failed", "cancelled"])
def test_checking_again_is_possible_after_a_session(page: Page, out: Path, final: str) -> None:
    controller = page.processing()
    if final == "cancelled":
        controller.cancel()
    results = {
        "done": clean_result(out),
        "failed": SessionResult(error=RuntimeError("x")),
        "cancelled": SessionResult(cancelled=True),
    }
    controller.on_finished(results[final])
    assert controller.can_check


def test_set_field_updates_the_form_the_errors_and_the_destination(page: Page, out: Path) -> None:
    controller = page.controller
    before = page.changes
    controller.set_field("album", "Rome")
    assert controller.form.album == "Rome"
    assert controller.destination is not None
    assert "Rome" in controller.destination
    assert page.changes == before + 1
    controller.set_field("album", "..")
    assert "album" in controller.errors
    assert controller.destination is None
    with pytest.raises(ValueError, match="no field"):
        controller.set_field("colour", "red")


def test_the_form_can_change_but_a_running_scan_keeps_the_form_it_started_with(
    page: Page,
) -> None:
    controller = page.scanning()
    started = page.worker.calls[-1][1]
    controller.set_field("album", "Later")
    assert started.album == ""


def test_closing_when_idle_is_immediate(page: Page) -> None:
    assert page.controller.request_close() is True


@pytest.mark.parametrize("starter", ["scanning", "processing"])
def test_closing_while_busy_cancels_first_and_waits(page: Page, starter: str) -> None:
    controller = page.scanning() if starter == "scanning" else page.processing()
    assert controller.request_close() is False
    assert controller.state is State.CANCELLING
    assert page.worker.names[-1] == "cancel"
    assert not controller.close_ready
    controller.on_finished(cancelled_scan(Path("/srv/demo/.raw/stamp")))
    assert controller.close_ready


def test_a_close_request_while_cancelling_just_waits(page: Page) -> None:
    controller = page.scanning()
    controller.cancel()
    assert controller.request_close() is False
    assert page.worker.names.count("cancel") == 1


def test_an_initial_valid_form_has_no_errors(out: Path, saved: list[ScanForm]) -> None:
    controller = Page(replace(ScanForm(), output_folder=str(out)), saved).controller
    assert controller.errors == {}
