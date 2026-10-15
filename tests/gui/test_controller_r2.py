"""Review round 2: a refused action changes nothing, a jam is not a lost scanner, the offers."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.state import ActionBlockedError, InvalidTransitionError, State
from fastfoto_linux.gui.worker import WorkerBusyError
from fastfoto_linux.scanner import (
    NoDocumentsError,
    ScanError,
    ScannerNotFoundError,
    ShimMissingError,
)
from fastfoto_linux.session import SessionResult, Stage
from tests.gui import test_controller
from tests.gui.helpers import FakeWorker, cancelled_scan
from tests.gui.test_controller import Page

LOAD_FEEDER = "Load photos in the feeder and press Scan"


saved = test_controller.saved  # the fixture


@pytest.fixture
def page(out: Path, saved: list[ScanForm]) -> Page:
    return Page(ScanForm(output_folder=str(out)), saved)


@dataclass
class BusyWorker(FakeWorker):
    """A worker that, while ``busy`` is set, refuses to start a check or processing."""

    busy: bool = False

    def check(self) -> None:
        if self.busy:
            raise WorkerBusyError("the scanner is busy with another job")
        super().check()

    def process_kept(self, kept: SessionResult) -> None:
        if self.busy:
            raise WorkerBusyError("the scanner is busy with another job")
        super().process_kept(kept)


# -- 1: an action that is not possible now is refused, it is not a failure -------------------


def test_the_blocked_actions_raise_a_distinct_error_that_is_still_a_transition_error(
    page: Page,
) -> None:
    controller = page.ready()
    for action in (controller.cancel, controller.process_kept):
        with pytest.raises(ActionBlockedError):
            action()
    assert issubclass(ActionBlockedError, InvalidTransitionError)
    controller.start_scan()
    for action in (controller.start_scan, controller.check_scanner):
        with pytest.raises(ActionBlockedError):
            action()
    assert controller.state is State.SCANNING


def test_a_failure_of_the_page_does_not_cancel_a_healthy_scan(page: Page) -> None:
    controller = page.scanning()
    controller.fail(RuntimeError("a slot broke"))
    assert "cancel" not in page.worker.names
    assert controller.state is State.SCANNING  # the scan goes on and reports as usual
    assert controller.banner is not None
    assert "a slot broke" in controller.banner.text


def test_a_failure_that_came_from_the_job_stops_it(page: Page) -> None:
    controller = page.scanning()
    controller.fail(RuntimeError("the event broke the page"), job=True)
    assert "cancel" in page.worker.names
    assert controller.state is State.FAILED


def test_a_failure_with_no_job_running_leaves_a_usable_failed_page(page: Page) -> None:
    controller = page.ready()
    controller.fail(RuntimeError("boom"))
    assert controller.state is State.FAILED
    assert "cancel" not in page.worker.names
    assert controller.can_check


def test_a_busy_worker_is_a_message_when_checking_the_scanner(
    out: Path, saved: list[ScanForm]
) -> None:
    controller = Controller(BusyWorker(busy=True), ScanForm(output_folder=str(out)))
    controller.check_scanner()
    assert controller.state is State.IDLE
    assert controller.banner is not None
    assert "busy" in controller.banner.text


def test_a_busy_worker_is_a_message_when_processing_kept_pages(out: Path) -> None:
    worker = BusyWorker()
    controller = Controller(worker, ScanForm(output_folder=str(out)))
    controller.check_scanner()
    controller.on_scanner(None)
    controller.start_scan()
    controller.cancel()
    controller.on_finished(cancelled_scan(Path("/srv/demo/.raw/x"), 2))
    worker.busy = True
    controller.process_kept()
    assert controller.state is State.CANCELLED
    assert controller.banner is not None
    assert "busy" in controller.banner.text
    assert controller.can_process_kept  # the offer is still there


# -- 2: only a lost scanner marks the scanner lost --------------------------------------------


@pytest.mark.parametrize("error", [ScanError("the paper jammed"), NoDocumentsError("empty")])
def test_a_jam_or_empty_feeder_in_the_result_keeps_the_scanner_found(
    page: Page, error: Exception
) -> None:
    controller = page.scanning()
    controller.on_finished(SessionResult(error=error))
    assert controller.state is State.FAILED
    assert controller.scanner_ready
    assert controller.can_scan
    assert controller.scanner_text == "Scanner found."
    assert controller.banner is not None
    assert controller.scanner_text not in controller.banner.text


def test_an_error_event_that_is_a_jam_keeps_the_scanner_found(page: Page) -> None:
    controller = page.scanning()
    controller.on_error(ScanError("the paper jammed"))
    assert controller.state is State.FAILED
    assert controller.scanner_ready
    assert controller.can_scan


def test_an_empty_feeder_says_what_to_do(page: Page) -> None:
    controller = page.scanning()
    controller.on_finished(SessionResult(error=NoDocumentsError("the document feeder is empty")))
    assert controller.banner is not None
    assert LOAD_FEEDER in controller.banner.text


@pytest.mark.parametrize("error", [ScannerNotFoundError("gone"), ShimMissingError("no shim")])
def test_a_lost_scanner_in_the_result_marks_the_scanner_lost_without_repeating_the_banner(
    page: Page, error: Exception
) -> None:
    controller = page.scanning()
    controller.on_finished(SessionResult(error=error))
    assert not controller.scanner_ready
    assert not controller.can_scan
    assert controller.banner is not None
    assert controller.scanner_text not in controller.banner.text


def test_a_lost_scanner_during_the_scan_is_still_no_scanner(page: Page) -> None:
    controller = page.scanning()
    controller.on_error(ScannerNotFoundError("gone"))
    assert controller.state is State.NO_SCANNER
    assert not controller.scanner_ready


# -- 10, 11: the words of the offers ----------------------------------------------------------


def test_the_offer_to_process_the_kept_pages_names_the_folder_of_the_scan_it_belongs_to(
    page: Page,
) -> None:
    controller = page.scanning()
    scanned_into = str(Path(controller.destination or "").parent)
    controller.cancel()
    controller.on_finished(cancelled_scan(Path("/srv/demo/.raw/stamp"), 3))
    controller.set_field("album", "Edited Later")  # not the folder the pages are processed into
    assert controller.process_kept_folder == scanned_into
    assert controller.can_process_kept


def test_the_button_that_processes_the_kept_pages_is_static_text_without_the_folder_name(
    out: Path, saved: list[ScanForm]
) -> None:
    """A button has no text format: a folder named ``<img ...>`` must not be in its text."""
    hostile = out / "<img src=x>"
    hostile.mkdir()
    controller = Page(ScanForm(output_folder=str(hostile)), saved).cancelled()
    assert controller.process_kept_text == "Process them now"
    assert controller.process_kept_folder == str(hostile)
    assert "<" not in controller.process_kept_text


def test_there_is_no_offer_text_without_an_offer(page: Page) -> None:
    controller = page.ready()
    assert controller.process_kept_text == ""
    assert controller.process_kept_folder == ""


def test_the_close_question_says_scan_or_processing_by_the_state(page: Page) -> None:
    controller = page.scanning()
    assert "scan" in controller.close_title.lower()
    assert "processing" not in controller.close_title.lower()
    controller.on_stage(Stage.PROCESSING)
    assert "processing" in controller.close_title.lower()
    assert "processing" in controller.close_text.lower()
