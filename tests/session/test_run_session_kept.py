"""``run_session``: the kept pages a front end can offer to process later, and how it settles."""

import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.scanner import ScanCancelledError
from fastfoto_linux.session import RawPolicy, RawReason, Stage
from fastfoto_linux.session import raw as session_raw
from fastfoto_linux.session.run import _failure_reason, _keep_reason, _Outcome
from tests.process_helpers import page_name, plain_sheet
from tests.session.conftest import STAMP, make_request, run


class Boom(Exception):
    pass


def boom(*args: Any, **kwargs: Any):
    raise Boom("processing blew up")


def two_sheets(transport):
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    return transport


def names(paths: tuple[Path, ...]) -> list[str]:
    return [p.name for p in paths]


def all_pages(count: int) -> list[str]:
    return [page_name(n) for n in range(1, count + 1)]


# --- kept_pages --------------------------------------------------------------------------------


def test_the_kept_pages_are_the_raw_pages_in_the_kept_folder_in_page_order(out, transport) -> None:
    session = run(make_request(out, policy=RawPolicy.KEEP), two_sheets(transport))
    assert session.raw_dir == out / ".raw" / STAMP
    assert session.kept_pages == tuple(session.raw_dir / name for name in all_pages(4))
    assert all(page.is_file() for page in session.kept_pages)
    assert len(session.kept_pages) == session.pages_scanned


def test_there_are_no_kept_pages_when_the_raw_pages_were_discarded(out, transport) -> None:
    session = run(make_request(out, policy=RawPolicy.DISCARD), two_sheets(transport))
    assert session.raw_dir is None
    assert session.kept_pages == ()


def test_a_cancelled_scan_lists_the_pages_scanned_so_far(out, transport) -> None:
    two_sheets(transport)
    transport.keep_on_disk = transport.pages_before_failure = 3
    transport.failure = lambda pages: ScanCancelledError("scan cancelled", pages=pages)
    session = run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert session.cancelled is True
    assert session.process is None
    assert names(session.kept_pages) == all_pages(3)
    assert all(page.parent == session.raw_dir for page in session.kept_pages)


def test_an_interrupted_scan_lists_the_pages_found_on_disk(out, transport) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    transport.pages_before_failure = 4
    transport.failure = lambda pages: KeyboardInterrupt()
    session = run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert session.cancelled is True
    assert names(session.kept_pages) == all_pages(4)


def test_a_cancel_while_processing_lists_all_the_pages(out, transport) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1), plain_sheet(2)]
    cancel = threading.Event()
    session = run(
        make_request(out, policy=RawPolicy.DISCARD),
        transport,
        cancel=cancel,
        on_photo=lambda files: cancel.set(),
    )
    assert session.process is not None
    assert session.process.photos == 1
    assert names(session.kept_pages) == all_pages(6)


def test_a_processing_error_lists_the_pages(out, transport) -> None:
    session = run(make_request(out, policy=RawPolicy.DISCARD), two_sheets(transport), process=boom)
    assert session.raw_reason is RawReason.ERROR
    assert names(session.kept_pages) == all_pages(4)


def test_pages_are_listed_by_page_number_and_other_files_are_not_pages(tmp_path) -> None:
    for name in ("page-0002.png", "page-0001.png", "page-10000.png", "page-9999.png"):
        (tmp_path / name).write_bytes(b"")
    for stray in ("notes.txt", "page-0003.png.part", "other-0001.png"):
        (tmp_path / stray).write_bytes(b"")
    (tmp_path / "page-0004.png").mkdir()
    assert names(session_raw.list_pages(tmp_path)) == [
        "page-0001.png",
        "page-0002.png",
        "page-9999.png",
        "page-10000.png",
    ]


def test_a_folder_that_cannot_be_listed_has_no_pages(tmp_path, caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="fastfoto_linux.session.raw"):
        assert session_raw.list_pages(tmp_path / "gone") == ()
    assert "gone" in caplog.text


# --- where the raw pages are flushed before they are deleted ----------------------------------


def watch_syncs(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    synced: list[Path] = []
    monkeypatch.setattr(session_raw, "sync_folders", synced.extend)
    return synced


def test_both_the_album_and_the_raw_folder_are_synced_before_the_pages_go(
    out, transport, tmp_path, monkeypatch
) -> None:
    home = tmp_path / "raw-home"
    home.mkdir()
    synced = watch_syncs(monkeypatch)
    request = make_request(out, policy=RawPolicy.DISCARD, raw_parent=home)
    session = run(request, two_sheets(transport))
    assert session.raw_reason is None
    assert set(synced) == {out, home}


def test_a_shared_folder_is_synced_once(out, transport, monkeypatch) -> None:
    synced = watch_syncs(monkeypatch)
    session = run(make_request(out, policy=RawPolicy.DISCARD), two_sheets(transport))
    assert session.raw_reason is None
    assert synced == [out]


# --- the reason when there is nothing to go on, and what is logged ----------------------------


def test_a_run_with_no_result_and_no_known_cause_keeps_the_pages() -> None:
    nothing = _Outcome()
    assert _failure_reason(nothing) is RawReason.ERROR
    assert _keep_reason(RawPolicy.DISCARD, nothing) is RawReason.ERROR


def test_the_exception_that_ended_the_work_is_logged_at_debug(out, transport, caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger="fastfoto_linux.session.run"):
        run(make_request(out), two_sheets(transport), process=boom)
    traced = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
    assert [r.exc_info[0] for r in traced if r.exc_info] == [Boom]


def test_an_interrupt_is_logged_at_debug_too(out, transport, caplog) -> None:
    transport.failure = lambda pages: KeyboardInterrupt()
    transport.sheets = [plain_sheet()]
    with caplog.at_level(logging.DEBUG, logger="fastfoto_linux.session.run"):
        run(make_request(out), transport)
    traced = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
    assert [r.exc_info[0] for r in traced if r.exc_info] == [KeyboardInterrupt]


# --- the enums read well in a log or a UI ------------------------------------------------------


def test_stages_and_reasons_are_strings() -> None:
    assert str(Stage.PROCESSING) == "processing"
    assert RawReason.SCAN_ERROR == "scan_error"
    assert f"{RawReason.BACK_DROPPED}" == "back_dropped"
    assert {reason.value for reason in RawReason} == {
        "cancelled",
        "scan_error",
        "error",
        "sheets_failed",
        "sheets_degraded",
        "requested",
        "back_dropped",
        "not_deleted",
    }


# --- only finished pages are kept pages -------------------------------------------------------


def cut_short(page: Path) -> None:
    """Leave ``page`` as a scanner killed part-way through writing it would."""
    page.write_bytes(page.read_bytes()[:100])


def test_a_cancelled_scan_lists_only_the_pages_the_scanner_finished(out, transport) -> None:
    two_sheets(transport)
    transport.pages_before_failure = 3

    def cancelled(pages: tuple[Path, ...]) -> BaseException:
        cut_short(pages[0].parent / page_name(4))
        return ScanCancelledError("scan cancelled", pages=pages)

    transport.failure = cancelled
    session = run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert names(session.kept_pages) == all_pages(3)
    assert (session.raw_dir / page_name(4)).is_file()  # still kept on disk, just not offered


def test_an_interrupted_scan_does_not_list_a_page_cut_off_mid_write(out, transport) -> None:
    two_sheets(transport)
    transport.pages_before_failure = 4

    def interrupted(pages: tuple[Path, ...]) -> BaseException:
        cut_short(pages[3])
        return KeyboardInterrupt()

    transport.failure = interrupted
    session = run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert session.cancelled is True
    assert names(session.kept_pages) == all_pages(3)


def test_a_png_is_complete_only_when_it_ends_with_the_end_chunk(tmp_path, out, transport) -> None:
    session = run(make_request(out, policy=RawPolicy.KEEP), two_sheets(transport))
    whole = session.kept_pages[0]
    assert session_raw.is_complete_png(whole) is True
    cut = tmp_path / "cut.png"
    cut.write_bytes(whole.read_bytes()[:-1])
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    assert session_raw.is_complete_png(cut) is False
    assert session_raw.is_complete_png(empty) is False
    assert session_raw.is_complete_png(tmp_path / "missing.png") is False


def test_a_cut_off_page_the_scanner_still_reported_is_not_listed(out, transport) -> None:
    # run_scan reports every page file on disk after a cancel, finished or not.
    two_sheets(transport)
    transport.pages_before_failure = 4

    def cancelled(pages: tuple[Path, ...]) -> BaseException:
        cut_short(pages[3])
        return ScanCancelledError("scan cancelled", pages=pages)

    transport.failure = cancelled
    session = run(make_request(out, policy=RawPolicy.DISCARD), transport)
    assert names(session.kept_pages) == all_pages(3)


def test_a_file_shorter_than_the_end_chunk_is_not_a_complete_png(tmp_path) -> None:
    short = tmp_path / "short.png"
    short.write_bytes(b"IEND")
    assert session_raw.is_complete_png(short) is False
