"""``run_session``: scan, process and settle the raw pages, reporting through callbacks."""

import errno
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from fastfoto_linux.pipeline.process import ProcessResult
from fastfoto_linux.scanner import (
    NoDocumentsError,
    ScanCancelledError,
    ScanError,
    Source,
)
from fastfoto_linux.session import RawPolicy, RawReason, Stage, run_session
from fastfoto_linux.session import raw as session_raw
from tests.cli.fakes import DEVICE, FakeTransport
from tests.process_helpers import jpeg_names, page_name, plain_sheet, written_sheet
from tests.session.conftest import (
    DPI,
    STAMP,
    Events,
    kept_names,
    make_request,
    raw_leftovers,
    run,
)


def jam(pages):
    return ScanError("paper jam", returncode=1, pages=pages)


def cancelled(pages):
    return ScanCancelledError("scan cancelled", pages=pages)


def ctrl_c(pages):
    return KeyboardInterrupt()


class ProcessingBlewUp(Exception):
    pass


def boom(*args: Any, **kwargs: Any) -> ProcessResult:
    raise ProcessingBlewUp("processing blew up")


def failing_enhancer(image, dpi):
    raise ValueError("restore exploded")


def must_not_run(*args: Any, **kwargs: Any) -> ProcessResult:
    raise AssertionError("the pages must not be processed")


def two_sheets(transport: FakeTransport) -> FakeTransport:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    return transport


# --- the happy path ---------------------------------------------------------------------------


def test_a_clean_run_scans_processes_and_leaves_no_raw_pages(out, transport) -> None:
    session = run(make_request(out), two_sheets(transport))
    assert session.ok is True
    assert session.process is not None
    assert session.process.photos == 2
    assert session.pages_scanned == 4
    assert (session.raw_dir, session.raw_reason, session.error) == (None, None, None)
    assert session.cancelled is False
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]
    assert raw_leftovers(out) == []


def test_the_scan_job_follows_the_request(out, transport) -> None:
    run(make_request(out), two_sheets(transport))
    (job,) = transport.jobs
    assert (job.device, job.resolution, job.source) == (DEVICE, DPI, Source.DUPLEX)
    assert job.output_dir.parent == out
    assert job.output_dir.name.startswith(session_raw.TEMP_PREFIX)


def test_a_simplex_request_scans_the_front_only(out, transport) -> None:
    transport.front_pages = 2
    session = run(make_request(out, duplex=False), transport)
    (job,) = transport.jobs
    assert job.source is Source.FRONT
    assert session.process is not None
    assert session.process.photos == 2
    assert session.pages_scanned == 2


def test_the_callbacks_hear_about_pages_stages_and_photos_in_order(out, transport) -> None:
    events = Events()
    session = run(make_request(out), two_sheets(transport), **events.callbacks())
    assert events.pages == [1, 2, 3, 4]
    assert events.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]
    assert session.process is not None
    assert events.photos == list(session.process.written)
    assert len(events.photos) == 2


def test_done_comes_after_the_raw_pages_were_settled(out, transport) -> None:
    hidden_at_done: list[list[str]] = []

    def on_stage(stage: Stage) -> None:
        if stage is Stage.DONE:
            hidden_at_done.append(raw_leftovers(out))

    run(make_request(out, policy=RawPolicy.DISCARD), two_sheets(transport), on_stage=on_stage)
    assert hidden_at_done == [[]]


def test_no_callbacks_are_needed(out, transport) -> None:
    assert run(make_request(out), two_sheets(transport)).ok is True


def test_the_scan_gets_the_page_callback_and_the_cancel_event(out, transport) -> None:
    received: list[dict[str, Any]] = []

    def scan(job, *, env, **kwargs):
        received.append(kwargs)
        return transport.run_scan(job, env=env, **kwargs)

    cancel, on_page = threading.Event(), lambda number: None
    two_sheets(transport)
    request = make_request(out)
    run_session(request, scan=scan, on_page=on_page, cancel=cancel)
    run_session(request, scan=scan)
    assert received[0]["cancel"] is cancel
    assert received[0]["on_progress"] is on_page
    assert received[1]["cancel"] is None
    assert received[1]["on_progress"] is None


def test_process_gets_only_the_options_that_were_given(out, transport) -> None:
    calls: list[dict[str, Any]] = []

    def process(pages, settings, **options) -> ProcessResult:
        calls.append(options)
        return ProcessResult()

    on_photo, cancel = (lambda files: None), threading.Event()
    transport.sheets = [plain_sheet(0)]
    run(make_request(out), transport, process=process)
    run(make_request(out), transport, process=process, on_photo=on_photo, cancel=cancel)
    assert calls == [{}, {"on_photo": on_photo, "cancel": cancel}]


def test_a_session_prints_nothing(out, transport, capsys) -> None:
    run(make_request(out), two_sheets(transport), **Events().callbacks())
    failing = FakeTransport(sheets=[plain_sheet(0)], pages_before_failure=1, failure=jam)
    run(make_request(out), failing)
    run(make_request(out), FakeTransport(sheets=[plain_sheet(0)]), process=boom)
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")


# --- the raw pages: when they stay and why -----------------------------------------------------


@dataclass(frozen=True)
class RawCase:
    """A scan and what the session must do with its raw pages."""

    policy: RawPolicy
    reason: RawReason | None
    sheets: tuple[Any, ...] = (plain_sheet(0), plain_sheet(1))
    kept_pages: int = 4
    transport: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)


RAW_CASES = {
    "clean, discard": RawCase(RawPolicy.DISCARD, None),
    "clean, auto": RawCase(RawPolicy.AUTO, None),
    "clean, keep": RawCase(RawPolicy.KEEP, RawReason.REQUESTED),
    "failed sheet": RawCase(
        RawPolicy.DISCARD, RawReason.SHEETS_FAILED, transport={"corrupt_page": 3}
    ),
    "degraded sheet": RawCase(
        RawPolicy.DISCARD, RawReason.SHEETS_DEGRADED, settings={"enhancers": (failing_enhancer,)}
    ),
    "dropped back, auto": RawCase(
        RawPolicy.AUTO, RawReason.BACK_DROPPED, sheets=(plain_sheet(0), written_sheet(1))
    ),
    "dropped back, discard": RawCase(
        RawPolicy.DISCARD, None, sheets=(plain_sheet(0), written_sheet(1))
    ),
    "dropped back, keep": RawCase(
        RawPolicy.KEEP, RawReason.REQUESTED, sheets=(plain_sheet(0), written_sheet(1))
    ),
    "scan error after 3 pages": RawCase(
        RawPolicy.DISCARD,
        RawReason.SCAN_ERROR,
        kept_pages=3,
        transport={"keep_on_disk": 3, "pages_before_failure": 3, "failure": jam},
    ),
    "cancelled scan": RawCase(
        RawPolicy.DISCARD,
        RawReason.CANCELLED,
        kept_pages=2,
        transport={"keep_on_disk": 2, "pages_before_failure": 2, "failure": cancelled},
    ),
    "interrupted scan": RawCase(
        RawPolicy.DISCARD,
        RawReason.CANCELLED,
        transport={"failure": ctrl_c},
    ),
}


@pytest.mark.parametrize("case", RAW_CASES.values(), ids=RAW_CASES.keys())
def test_the_raw_pages_stay_exactly_when_the_run_was_not_clean(out, case: RawCase) -> None:
    transport = FakeTransport(sheets=case.sheets, **case.transport)
    session = run(make_request(out, policy=case.policy, **case.settings), transport)
    assert session.raw_reason is case.reason
    if case.reason is None:
        assert session.raw_dir is None
        assert raw_leftovers(out) == []
    else:
        assert session.raw_dir == out / ".raw" / STAMP
        assert kept_names(session.raw_dir) == [page_name(n) for n in range(1, case.kept_pages + 1)]
        assert raw_leftovers(out) == [".raw"]


def test_a_failed_delete_is_reported_as_pages_that_could_not_be_deleted(
    out, transport, monkeypatch
) -> None:
    def refuse(folders):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(session_raw, "sync_folders", refuse)
    session = run(make_request(out, policy=RawPolicy.DISCARD), two_sheets(transport))
    assert session.ok is True
    assert session.raw_reason is RawReason.NOT_DELETED
    assert session.raw_dir is not None
    assert kept_names(session.raw_dir) == [page_name(n) for n in range(1, 5)]


def test_the_raw_pages_live_under_the_raw_parent_when_there_is_one(
    out, transport, tmp_path
) -> None:
    home = tmp_path / "raw-home"
    home.mkdir()
    session = run(make_request(out, policy=RawPolicy.KEEP, raw_parent=home), two_sheets(transport))
    assert session.raw_dir == home / ".raw" / STAMP
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]
    assert raw_leftovers(out) == []


# --- partial scans, cancels and errors ---------------------------------------------------------


def test_the_pages_scanned_before_a_scanner_failure_are_still_processed(out, transport) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    transport.keep_on_disk = transport.pages_before_failure = 3
    transport.failure = jam
    events = Events()
    session = run(make_request(out), transport, **events.callbacks())
    assert isinstance(session.error, ScanError)
    assert session.pages_scanned == 3
    assert session.process is not None
    assert session.process.photos == 2  # the third page is a front without its back
    assert len(session.process.uncertain) == 1
    assert session.cancelled is False
    assert session.ok is False
    assert events.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]


@pytest.mark.parametrize("failure", [cancelled, ctrl_c], ids=["cancelled", "interrupted"])
def test_a_cancelled_scan_is_not_processed_and_keeps_its_pages(out, transport, failure) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    transport.failure = failure
    transport.pages_before_failure = 2
    events = Events()
    session = run(make_request(out), transport, process=must_not_run, **events.callbacks())
    assert session.cancelled is True
    assert session.error is None
    assert session.process is None
    assert session.ok is False
    assert events.stages == [Stage.SCANNING, Stage.DONE]
    assert jpeg_names(out) == []
    assert kept_names(session.raw_dir) == [page_name(n) for n in range(1, 5)]


def test_a_cancel_while_processing_stops_between_sheets_and_keeps_the_pages(out, transport) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1), plain_sheet(2)]
    cancel = threading.Event()
    events = Events()
    session = run(
        make_request(out, policy=RawPolicy.DISCARD),
        transport,
        cancel=cancel,
        on_photo=lambda files: (events.photos.append(files), cancel.set()),
        on_stage=events.stages.append,
    )
    assert session.cancelled is True
    assert session.process is not None
    assert session.process.cancelled is True
    assert session.process.photos == 1
    assert len(events.photos) == 1
    assert session.raw_reason is RawReason.CANCELLED
    assert len(kept_names(session.raw_dir)) == 6
    assert events.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]
    assert session.ok is False


def test_an_unexpected_error_while_processing_comes_back_and_keeps_the_pages(
    out, transport
) -> None:
    events = Events()
    session = run(
        make_request(out, policy=RawPolicy.DISCARD),
        two_sheets(transport),
        process=boom,
        **events.callbacks(),
    )
    assert isinstance(session.error, ProcessingBlewUp)
    assert session.cancelled is False
    assert session.process is None
    assert session.pages_scanned == 4
    assert session.raw_reason is RawReason.ERROR
    assert len(kept_names(session.raw_dir)) == 4
    assert events.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]
    assert session.ok is False


def test_an_exception_from_on_photo_stops_the_session_and_comes_back(out, transport) -> None:
    def refuse(files):
        raise ProcessingBlewUp("the window is gone")

    session = run(make_request(out), two_sheets(transport), on_photo=refuse)
    assert isinstance(session.error, ProcessingBlewUp)
    assert session.raw_reason is RawReason.ERROR
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]


def test_an_exception_from_on_page_stops_the_session_and_comes_back(out, transport) -> None:
    def refuse(number):
        raise ProcessingBlewUp("the window is gone")

    session = run(make_request(out), two_sheets(transport), on_page=refuse)
    assert isinstance(session.error, ProcessingBlewUp)
    assert session.process is None
    assert session.raw_reason is RawReason.ERROR
    assert jpeg_names(out) == []


def test_a_scanner_failure_before_any_page_leaves_nothing_but_the_error(out, transport) -> None:
    error = NoDocumentsError("the document feeder is empty")
    transport.failure = lambda pages: error
    events = Events()
    session = run(make_request(out), transport, **events.callbacks())
    assert session.error is error
    assert session.process is None
    assert session.pages_scanned == 0
    assert (session.raw_dir, session.raw_reason) == (None, None)
    assert raw_leftovers(out) == []
    assert events.stages == [Stage.SCANNING, Stage.DONE]


def test_a_scanner_failure_without_pages_still_keeps_the_files_found_on_disk(
    out, transport
) -> None:
    transport.sheets = [plain_sheet()]
    transport.pages_before_failure = 0
    transport.failure = jam
    session = run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert isinstance(session.error, ScanError)
    assert session.process is None
    assert session.raw_reason is RawReason.SCAN_ERROR
    assert kept_names(session.raw_dir) == [page_name(1), page_name(2)]


def test_a_scan_that_delivers_no_pages_is_an_empty_session_like_the_cli_one(out, transport) -> None:
    events = Events()
    session = run(make_request(out), transport, **events.callbacks())
    assert session.process == ProcessResult()
    assert session.pages_scanned == 0
    assert session.ok is True
    assert events.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]
    assert raw_leftovers(out) == []


def test_a_missing_output_folder_is_an_error_not_a_crash(out, transport, tmp_path) -> None:
    missing = tmp_path / "gone"
    request = make_request(missing, raw_parent=out)
    session = run(request, two_sheets(transport))
    assert session.error is not None
    assert "does not exist" in str(session.error)
    assert session.raw_reason is RawReason.ERROR
    assert len(kept_names(session.raw_dir)) == 4


def test_the_result_is_frozen(out, transport) -> None:
    session = run(make_request(out), two_sheets(transport))
    with pytest.raises(AttributeError):
        session.cancelled = True
