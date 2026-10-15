import threading
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.gui import worker as worker_module
from fastfoto_linux.gui.form import FormInvalidError, ScanForm
from fastfoto_linux.gui.worker import Worker, WorkerBusyError
from fastfoto_linux.pipeline.process import ProcessResult, ProcessSettings
from fastfoto_linux.scanner import ScannerNotFoundError, ScanTarget
from fastfoto_linux.session import RawReason, ScanRequest, SessionResult, Stage
from tests.cli.fakes import DEVICE
from tests.gui.helpers import RecordingSink, cancelled_scan, clean_result, written

WAIT = 10.0


@pytest.fixture
def form(out: Path) -> ScanForm:
    return ScanForm(output_folder=str(out))


def found() -> ScanTarget:
    return ScanTarget(device=DEVICE)


class FakeSession:
    """Stands in for run_session: plays a script of callbacks, then returns a result."""

    def __init__(self, result: SessionResult, out: Path) -> None:
        self.result = result
        self.out = out
        self.requests: list[ScanRequest] = []
        self.cancels: list[threading.Event] = []

    def __call__(self, request: ScanRequest, **hooks: Any) -> SessionResult:
        self.requests.append(request)
        self.cancels.append(hooks["cancel"])
        hooks["on_stage"](Stage.SCANNING)
        hooks["on_page"](1)
        hooks["on_page"](2)
        hooks["on_stage"](Stage.PROCESSING)
        hooks["on_photo"](written(self.out, 1))
        hooks["on_stage"](Stage.DONE)
        return self.result


def worker_for(sink: RecordingSink, **fakes: Any) -> Worker:
    fakes.setdefault("discover", found)
    return Worker(sink, **fakes)


def test_check_reports_a_found_scanner_from_another_thread() -> None:
    sink = RecordingSink()
    worker = worker_for(sink)
    worker.check()
    worker.join(WAIT)
    assert sink.events == [("scanner", None)]
    assert sink.threads[0] != threading.get_ident()


def test_check_reports_why_no_scanner_was_found() -> None:
    error = ScannerNotFoundError("no FF-680W found on USB")

    def missing() -> ScanTarget:
        raise error

    sink = RecordingSink()
    worker = worker_for(sink, discover=missing)
    worker.check()
    worker.join(WAIT)
    assert sink.events == [("scanner", error)]


def test_a_scan_reports_in_the_order_the_session_does(out: Path, form: ScanForm) -> None:
    sink = RecordingSink()
    result = clean_result(out)
    session = FakeSession(result, out)
    worker = worker_for(sink, session=session)
    worker.scan(form)
    worker.join(WAIT)
    assert sink.names == [
        "stage",
        "page",
        "page",
        "stage",
        "photo",
        "stage",
        "finished",
    ]
    assert [v for n, v in sink.events if n == "stage"] == [
        Stage.SCANNING,
        Stage.PROCESSING,
        Stage.DONE,
    ]
    assert sink.value("finished") is result
    assert len(set(sink.threads)) == 1
    assert sink.threads[0] != threading.get_ident()


def test_the_scan_request_is_the_forms_for_the_scanner_found(out: Path, form: ScanForm) -> None:
    session = FakeSession(clean_result(out), out)
    worker = worker_for(RecordingSink(), session=session)
    worker.scan(replace(form, album="Rome", dpi=300))
    worker.join(WAIT)
    (request,) = session.requests
    assert request.target.device == DEVICE
    assert request.dpi == 300
    assert request.settings.album == "Rome"
    assert request.settings.output_root == out


def test_an_invalid_form_is_refused_before_anything_starts() -> None:
    sink = RecordingSink()
    session = FakeSession(SessionResult(), Path())
    worker = worker_for(sink, session=session)
    with pytest.raises(FormInvalidError):
        worker.scan(ScanForm())
    assert not worker.busy
    assert sink.events == []
    assert session.requests == []


def test_a_cancel_from_another_thread_stops_the_session(out: Path, form: ScanForm) -> None:
    started = threading.Event()
    raw = out / ".raw" / "stamp"

    def session(request: ScanRequest, **hooks: Any) -> SessionResult:
        started.set()
        assert hooks["cancel"].wait(WAIT), "the worker never set the cancel event"
        return cancelled_scan(raw)

    sink = RecordingSink()
    worker = worker_for(sink, session=session)
    worker.scan(form)
    assert started.wait(WAIT)
    assert worker.busy
    threading.Thread(target=worker.cancel).start()
    worker.join(WAIT)
    result = sink.value("finished")
    assert result.cancelled
    assert result.kept_pages
    assert not worker.busy


def test_a_scanner_that_vanished_by_scan_time_is_an_error_and_no_session_runs(
    out: Path, form: ScanForm
) -> None:
    error = ScannerNotFoundError("gone")

    def missing() -> ScanTarget:
        raise error

    session = FakeSession(SessionResult(), out)
    sink = RecordingSink()
    worker = worker_for(sink, discover=missing, session=session)
    worker.scan(form)
    worker.join(WAIT)
    assert sink.events == [("error", error)]
    assert session.requests == []


def test_a_session_that_raises_still_reports_and_frees_the_worker(
    out: Path, form: ScanForm
) -> None:
    error = OSError("cannot create the raw folder")

    def broken(request: ScanRequest, **hooks: Any) -> SessionResult:
        raise error

    sink = RecordingSink()
    worker = worker_for(sink, session=broken)
    worker.scan(form)
    worker.join(WAIT)
    assert sink.events == [("error", error)]
    assert not worker.busy


def test_a_second_job_while_one_runs_is_refused(out: Path, form: ScanForm) -> None:
    release = threading.Event()

    def slow(request: ScanRequest, **hooks: Any) -> SessionResult:
        release.wait(WAIT)
        return SessionResult()

    worker = worker_for(RecordingSink(), session=slow)
    worker.scan(form)
    try:
        for start in (worker.check, lambda: worker.scan(form)):
            with pytest.raises(WorkerBusyError):
                start()
    finally:
        release.set()
        worker.join(WAIT)


def test_each_job_gets_a_fresh_cancel_event(out: Path, form: ScanForm) -> None:
    session = FakeSession(SessionResult(), out)
    worker = worker_for(RecordingSink(), session=session)
    worker.scan(form)
    worker.join(WAIT)
    worker.cancel()  # nothing is running: harmless
    worker.scan(form)
    worker.join(WAIT)
    first, second = session.cancels
    assert first is not second
    assert not second.is_set()


class FakeProcess:
    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.calls: list[tuple[Sequence[Path], ProcessSettings, dict[str, Any]]] = []

    def __call__(
        self, pages: Sequence[Path], settings: ProcessSettings, **hooks: Any
    ) -> ProcessResult:
        self.calls.append((pages, settings, hooks))
        for number in (1, 2):
            hooks["on_photo"](written(settings.output_root, number))
        return self.result


def test_kept_pages_are_processed_with_the_settings_of_the_scan(out: Path, form: ScanForm) -> None:
    raw = out / ".raw" / "stamp"
    kept = cancelled_scan(raw)
    processed = ProcessResult(written=(written(out, 1), written(out, 2)))
    process = FakeProcess(processed)
    session = FakeSession(kept, out)
    sink = RecordingSink()
    worker = worker_for(sink, session=session, process=process)
    worker.scan(replace(form, album="Rome"))
    worker.join(WAIT)
    sink.events.clear()
    worker.process_kept(kept)
    worker.join(WAIT)
    ((pages, settings, hooks),) = process.calls
    assert tuple(pages) == kept.kept_pages
    assert settings == session.requests[0].settings
    assert isinstance(hooks["cancel"], threading.Event)
    assert sink.names == ["stage", "photo", "photo", "finished"]
    assert sink.value("stage") is Stage.PROCESSING
    done: SessionResult = sink.value("finished")
    assert done.process is processed
    assert not done.cancelled
    assert done.raw_dir == raw
    assert done.raw_reason is RawReason.CANCELLED
    assert done.kept_pages == ()  # processed: nothing left to offer


def test_cancelling_the_processing_of_kept_pages_is_reported(out: Path, form: ScanForm) -> None:
    kept = cancelled_scan(out / ".raw" / "stamp")
    process = FakeProcess(ProcessResult(written=(written(out, 1),), cancelled=True))
    sink = RecordingSink()
    worker = worker_for(sink, session=FakeSession(kept, out), process=process)
    worker.scan(form)
    worker.join(WAIT)
    worker.process_kept(kept)
    worker.join(WAIT)
    assert sink.value("finished").cancelled


def test_kept_pages_cannot_be_processed_before_a_scan_made_settings(out: Path) -> None:
    worker = worker_for(RecordingSink(), process=FakeProcess(ProcessResult()))
    with pytest.raises(RuntimeError, match="no scan"):
        worker.process_kept(cancelled_scan(out))


def test_processing_that_raises_is_reported(out: Path, form: ScanForm) -> None:
    kept = cancelled_scan(out / ".raw" / "stamp")
    error = RuntimeError("disk full")

    def broken(pages: Sequence[Path], settings: ProcessSettings, **hooks: Any) -> ProcessResult:
        raise error

    sink = RecordingSink()
    worker = worker_for(sink, session=FakeSession(kept, out), process=broken)
    worker.scan(form)
    worker.join(WAIT)
    sink.events.clear()
    worker.process_kept(kept)
    worker.join(WAIT)
    assert sink.events == [("stage", Stage.PROCESSING), ("error", error)]


def test_the_default_discovery_looks_for_the_usb_scanner_and_its_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def resolve(**kwargs: Any) -> ScanTarget:
        calls.append(kwargs)
        return found()

    monkeypatch.setattr(worker_module, "resolve_target", resolve)
    monkeypatch.setenv("HOME", "/nonexistent-home")
    assert worker_module.default_discover() == found()
    (call,) = calls
    assert call["net_host"] is None
    assert (
        Path("/nonexistent-home/.local/lib/fastfoto-linux/ff680w_usb_gap.so")
        in call["shim_candidates"]
    )


def test_the_worker_uses_the_real_collaborators_unless_given_fakes(
    monkeypatch: pytest.MonkeyPatch, out: Path, form: ScanForm
) -> None:
    seen: list[str] = []

    def discover() -> ScanTarget:
        seen.append("discover")
        return found()

    def session(request: ScanRequest, **hooks: Any) -> SessionResult:
        seen.append("session")
        return SessionResult()

    monkeypatch.setattr(worker_module, "default_discover", discover)
    monkeypatch.setattr(worker_module, "run_session", session)
    sink = RecordingSink()
    worker = Worker(sink)
    worker.scan(form)
    worker.join(WAIT)
    assert seen == ["discover", "session"]
    assert isinstance(sink.value("finished"), SessionResult)
