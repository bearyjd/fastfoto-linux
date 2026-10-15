"""``run_session`` when a clean finish does not end it: aborts, callbacks, interrupts."""

import asyncio
import logging
import threading
from typing import Any

import pytest

from fastfoto_linux.pipeline.process import ProcessResult
from fastfoto_linux.scanner import ScanError
from fastfoto_linux.session import RawPolicy, RawReason, Stage
from tests.process_helpers import jpeg_names, page_name, plain_sheet
from tests.session.conftest import STAMP, Events, kept_names, make_request, raw_leftovers, run


class Abort(BaseException):  # stands for a private abort
    pass


class WindowGone(Exception):
    pass


ABORTS = {
    "SystemExit": SystemExit,
    "private abort": Abort,
    "CancelledError": asyncio.CancelledError,
}


def exit_process(*args: Any, **kwargs: Any) -> ProcessResult:
    raise SystemExit(3)


def window_gone_at_done(stage: Stage) -> None:
    if stage is Stage.DONE:
        raise WindowGone("the window is gone")


def two_sheets(transport):
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    return transport


def all_pages(count: int) -> list[str]:
    return [page_name(n) for n in range(1, count + 1)]


# --- a BaseException that is not an Exception: it propagates, the raw pages are kept ----------


@pytest.mark.parametrize("abort", ABORTS.values(), ids=ABORTS.keys())
def test_an_abort_while_scanning_propagates_and_keeps_the_raw_pages(out, transport, abort) -> None:
    two_sheets(transport)
    transport.pages_before_failure = 4
    transport.failure = lambda pages: abort()
    with pytest.raises(abort):
        run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert raw_leftovers(out) == [".raw"]
    assert kept_names(out / ".raw" / STAMP) == all_pages(4)


def test_an_abort_while_processing_propagates_and_keeps_the_raw_pages(out, transport) -> None:
    with pytest.raises(SystemExit):
        run(
            make_request(out, policy=RawPolicy.DISCARD), two_sheets(transport), process=exit_process
        )
    assert raw_leftovers(out) == [".raw"]
    assert kept_names(out / ".raw" / STAMP) == all_pages(4)


def test_an_abort_from_on_photo_keeps_the_raw_pages_and_the_photos_written(out, transport) -> None:
    def leave(files):
        raise SystemExit(3)

    with pytest.raises(SystemExit):
        run(make_request(out, policy=RawPolicy.DISCARD), two_sheets(transport), on_photo=leave)
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]
    assert raw_leftovers(out) == [".raw"]
    assert kept_names(out / ".raw" / STAMP) == all_pages(4)


def test_an_abort_says_where_the_raw_pages_are_since_no_result_is_returned(
    out, transport, caplog
) -> None:
    transport.failure = lambda pages: SystemExit(3)
    transport.sheets = [plain_sheet()]
    with (
        caplog.at_level(logging.ERROR, logger="fastfoto_linux.session.run"),
        pytest.raises(SystemExit),
    ):
        run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert str(out / ".raw" / STAMP) in caplog.text


def test_a_failure_to_settle_never_replaces_the_abort(out, transport, monkeypatch, caplog) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise OSError("the disk is gone")

    monkeypatch.setattr("fastfoto_linux.session.run.settle_raw_dir", refuse)
    transport.failure = lambda pages: SystemExit(3)
    transport.sheets = [plain_sheet()]
    with (
        caplog.at_level(logging.ERROR, logger="fastfoto_linux.session.run"),
        pytest.raises(SystemExit) as raised,
    ):
        run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert raised.value.code == 3
    assert "the disk is gone" in caplog.text


# --- the DONE callback ------------------------------------------------------------------------


def test_an_exception_from_the_done_callback_comes_back_with_the_result(
    out, transport, caplog
) -> None:
    with caplog.at_level(logging.ERROR, logger="fastfoto_linux.session.run"):
        session = run(
            make_request(out, policy=RawPolicy.DISCARD),
            two_sheets(transport),
            on_stage=window_gone_at_done,
        )
    assert isinstance(session.error, WindowGone)
    assert session.process is not None
    assert session.process.photos == 2
    assert session.pages_scanned == 4
    assert session.cancelled is False
    assert session.ok is False
    assert raw_leftovers(out) == []
    assert "the window is gone" in caplog.text


def test_an_earlier_error_is_not_replaced_by_one_from_the_done_callback(out, transport) -> None:
    two_sheets(transport)
    transport.keep_on_disk = transport.pages_before_failure = 3
    transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)
    session = run(make_request(out), transport, on_stage=window_gone_at_done)
    assert isinstance(session.error, ScanError)
    assert session.raw_reason is RawReason.SCAN_ERROR
    assert session.process is not None


def test_a_done_callback_that_raises_still_lets_the_stages_through_in_order(out, transport) -> None:
    events = Events()

    def on_stage(stage: Stage) -> None:
        events.stages.append(stage)
        window_gone_at_done(stage)

    run(make_request(out), two_sheets(transport), on_stage=on_stage)
    assert events.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]


# --- interrupts during processing, and a cancel that comes too late ---------------------------


def test_an_interrupt_while_processing_is_a_cancel_and_keeps_the_pages(out, transport) -> None:
    def interrupt(*args: Any, **kwargs: Any) -> ProcessResult:
        raise KeyboardInterrupt

    events = Events()
    session = run(
        make_request(out, policy=RawPolicy.DISCARD),
        two_sheets(transport),
        process=interrupt,
        **events.callbacks(),
    )
    assert session.cancelled is True
    assert session.error is None
    assert session.process is None
    assert session.pages_scanned == 4
    assert session.raw_reason is RawReason.CANCELLED
    assert kept_names(session.raw_dir) == all_pages(4)
    assert events.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]


def test_an_interrupt_from_on_photo_leaves_the_written_photos_and_the_pages(out, transport) -> None:
    def interrupt(files):
        raise KeyboardInterrupt

    session = run(
        make_request(out, policy=RawPolicy.DISCARD), two_sheets(transport), on_photo=interrupt
    )
    assert session.cancelled is True
    assert session.process is None  # the photos written before the interrupt are not listed
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]
    assert session.raw_reason is RawReason.CANCELLED
    assert kept_names(session.raw_dir) == all_pages(4)


def test_a_cancel_during_the_last_sheet_gives_a_complete_result_that_is_not_cancelled(
    out, transport
) -> None:
    cancel = threading.Event()
    seen: list[Any] = []

    def on_photo(files) -> None:
        seen.append(files)
        if len(seen) == 2:  # the last sheet: nothing is left that could still be stopped
            cancel.set()

    session = run(
        make_request(out, policy=RawPolicy.DISCARD),
        two_sheets(transport),
        cancel=cancel,
        on_photo=on_photo,
    )
    assert cancel.is_set()
    assert session.cancelled is False
    assert session.process is not None
    assert session.process.cancelled is False
    assert session.process.photos == 2
    assert session.ok is True
    assert (session.raw_dir, session.raw_reason) == (None, None)
    assert raw_leftovers(out) == []
