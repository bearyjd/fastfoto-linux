"""``process_pages``: the ``on_photo`` callback and the ``cancel`` event the desktop app drives."""

import threading
from pathlib import Path

import pytest

from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import ProcessResult, process_pages
from tests.process_helpers import jpeg_names, plain_sheet, settings_for, workspace, write_sheets


class PhotoCallbackError(Exception):
    """What a misbehaving ``on_photo`` raises."""


def batch(tmp_path: Path, sheets: int = 3) -> tuple[list[Path], Path]:
    """``(pages, output root)`` for ``sheets`` plain face-down sheets."""
    raw, out = workspace(tmp_path)
    return write_sheets(raw, [plain_sheet(seed) for seed in range(sheets)]), out


def test_on_photo_gets_each_written_photo_in_order(tmp_path) -> None:
    pages, out = batch(tmp_path)
    seen: list[WrittenFiles] = []
    result = process_pages(pages, settings_for(out), on_photo=seen.append)
    assert result.photos == 3
    assert seen == list(result.written)


def test_on_photo_runs_right_after_the_files_are_written(tmp_path) -> None:
    pages, out = batch(tmp_path)
    on_disk_at_call: list[int] = []

    def record(files: WrittenFiles) -> None:
        assert all(path.is_file() for path in files.paths)
        on_disk_at_call.append(len(jpeg_names(out)))

    process_pages(pages, settings_for(out), on_photo=record)
    assert on_disk_at_call == [1, 2, 3]


def test_on_photo_runs_on_the_calling_thread(tmp_path) -> None:
    pages, out = batch(tmp_path, sheets=1)
    threads: list[int] = []
    process_pages(
        pages, settings_for(out), on_photo=lambda files: threads.append(threading.get_ident())
    )
    assert threads == [threading.get_ident()]


def test_a_failed_sheet_is_not_announced(tmp_path) -> None:
    pages, out = batch(tmp_path)
    pages[2].write_bytes(b"not a png")  # the second sheet's front
    seen: list[WrittenFiles] = []
    result = process_pages(pages, settings_for(out), on_photo=seen.append)
    assert len(result.failed) == 1
    assert len(seen) == 2
    assert seen == list(result.written)


def test_an_exception_from_on_photo_propagates_after_the_photo_was_written(tmp_path) -> None:
    pages, out = batch(tmp_path)

    def refuse(files: WrittenFiles) -> None:
        raise PhotoCallbackError("the window is gone")

    with pytest.raises(PhotoCallbackError, match="the window is gone"):
        process_pages(pages, settings_for(out), on_photo=refuse)
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]  # not turned into a failed sheet, no more work


def test_a_cancel_set_before_the_start_writes_nothing(tmp_path) -> None:
    pages, out = batch(tmp_path)
    cancel = threading.Event()
    cancel.set()
    result = process_pages(pages, settings_for(out), cancel=cancel)
    assert result.cancelled is True
    assert result.photos == 0
    assert result.failed == ()
    assert jpeg_names(out) == []
    assert result.ok is False


def test_a_cancel_set_after_the_first_photo_stops_with_that_photo(tmp_path) -> None:
    pages, out = batch(tmp_path)
    cancel = threading.Event()
    seen: list[WrittenFiles] = []

    def stop_after_the_first(files: WrittenFiles) -> None:
        seen.append(files)
        cancel.set()

    result = process_pages(pages, settings_for(out), on_photo=stop_after_the_first, cancel=cancel)
    assert result.cancelled is True
    assert result.photos == 1
    assert seen == list(result.written)
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]
    assert result.ok is False


def test_a_cancel_from_another_thread_is_seen_between_sheets(tmp_path) -> None:
    pages, out = batch(tmp_path)
    cancel, first_photo = threading.Event(), threading.Event()

    def cancel_once_the_first_photo_is_written() -> None:
        assert first_photo.wait(timeout=5)
        cancel.set()

    def hold_the_first_photo(files: WrittenFiles) -> None:
        first_photo.set()
        assert cancel.wait(timeout=5), "the other thread never set the event"

    canceller = threading.Thread(target=cancel_once_the_first_photo_is_written)
    canceller.start()
    result = process_pages(pages, settings_for(out), on_photo=hold_the_first_photo, cancel=cancel)
    canceller.join()
    assert result.cancelled is True
    assert result.photos == 1


def test_a_cancel_during_the_last_photo_does_not_make_a_complete_run_cancelled(tmp_path) -> None:
    pages, out = batch(tmp_path, sheets=2)
    cancel = threading.Event()
    result = process_pages(
        pages,
        settings_for(out),
        on_photo=lambda files: cancel.set() if files.index == 2 else None,
        cancel=cancel,
    )
    assert result.photos == 2
    assert result.cancelled is False
    assert result.ok is True


def test_an_event_that_is_never_set_changes_nothing(tmp_path) -> None:
    pages, out = batch(tmp_path)
    result = process_pages(pages, settings_for(out), cancel=threading.Event())
    assert result.photos == 3
    assert result.cancelled is False
    assert result.ok is True


def test_a_plain_result_is_not_cancelled() -> None:
    assert ProcessResult().cancelled is False
    assert ProcessResult().ok is True
