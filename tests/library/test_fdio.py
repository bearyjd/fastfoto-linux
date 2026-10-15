"""Error paths of the descriptor-based reading and writing, and of the manifest."""

import errno
import logging
import os
import stat
from pathlib import Path

import pytest

from fastfoto_linux.library import fdio
from fastfoto_linux.library import manifest as manifest_module
from fastfoto_linux.library.apply import (
    REASON_IO,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_STALE,
    STATUS_UNLOGGED,
    STATUS_WRITTEN,
    apply_plan,
)
from fastfoto_linux.library.safety import UnsafePathError
from fastfoto_linux.library.summary import format_fix
from tests.library.apply_helpers import FIRST, SECOND, statuses, two_rows
from tests.library.jpeg_helpers import manifest_files, rotate_row, write_file

NOT_ROOT = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


def outcome(result, path: str) -> tuple[str, str]:
    (found,) = [o for o in result.outcomes if o.path == path]
    return found.status, found.reason


def test_a_file_that_changes_size_while_being_read_is_not_returned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = write_file(tmp_path, "a.bin", b"0123456789")
    real_fstat = os.fstat

    def shrunk(fd: int) -> os.stat_result:
        info = list(real_fstat(fd))
        info[stat.ST_SIZE] -= 1
        return os.stat_result(info)

    monkeypatch.setattr(os, "fstat", shrunk)
    with pytest.raises(fdio.ChangedWhileReadingError):
        fdio.read_regular(path)


def test_a_destination_that_is_the_library_is_refused_and_its_descriptor_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(UnsafePathError):
        fdio.open_root(tmp_path, os.stat(tmp_path))


def test_a_file_changed_while_it_is_read_makes_that_row_stale(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    def changed(_path: Path) -> None:
        raise fdio.ChangedWhileReadingError(errno.EAGAIN, "changed")

    row = rotate_row(lib, FIRST, 90, 1, 6)
    monkeypatch.setattr(fdio, "read_regular", changed)
    assert statuses(apply_plan([row], lib, dest)) == {FIRST: STATUS_STALE}


@NOT_ROOT
def test_an_unreadable_source_fails_that_row_alone(lib: Path, dest: Path) -> None:
    rows = two_rows(lib)
    (lib / FIRST).chmod(0)
    try:
        result = apply_plan(rows, lib, dest)
    finally:
        (lib / FIRST).chmod(0o644)
    assert outcome(result, FIRST) == (STATUS_FAILED, REASON_IO)
    assert outcome(result, SECOND) == (STATUS_WRITTEN, "")


@NOT_ROOT
def test_an_existing_file_that_cannot_be_read_is_reported_as_existing(
    lib: Path, dest: Path
) -> None:
    target = write_file(dest, FIRST, b"locked")
    target.chmod(0)
    try:
        result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    finally:
        target.chmod(0o644)
    assert statuses(result) == {FIRST: STATUS_EXISTS}


def test_a_filesystem_that_refuses_chmod_still_gets_the_copies_and_one_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, lib: Path, dest: Path
) -> None:
    def refuse(*_args: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    rows = two_rows(lib)
    monkeypatch.setattr(os, "fchmod", refuse)
    fdio._warn_modes_unsupported.cache_clear()
    with caplog.at_level(logging.WARNING, logger=fdio.logger.name):
        result = apply_plan(rows, lib, dest)
    assert statuses(result) == {FIRST: STATUS_WRITTEN, SECOND: STATUS_WRITTEN}
    assert (dest / FIRST).stat().st_mtime_ns == rows[0].mtime_ns
    warnings = [r for r in caplog.records if "permissions" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.parametrize("failing", ["fchmod", "link"])
def test_any_other_write_error_fails_the_row_and_leaves_nothing_behind(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path, failing: str
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(os, failing, broken)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert outcome(result, FIRST) == (STATUS_FAILED, REASON_IO)
    assert [p for p in dest.rglob("*") if p.is_file()] == []


def test_a_failed_swap_on_a_filesystem_without_links_releases_the_claimed_name(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    def no_links(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    def no_rename(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(os, "link", no_links)
    monkeypatch.setattr(os, "rename", no_rename)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert outcome(result, FIRST) == (STATUS_FAILED, REASON_IO)
    assert [p for p in dest.rglob("*") if p.is_file()] == []


def test_a_filesystem_that_cannot_sync_folders_still_gets_the_copy(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    real_fsync = os.fsync

    def files_only(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "Invalid argument")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", files_only)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_WRITTEN}


def test_a_folder_that_is_a_plain_file_is_refused(lib: Path, dest: Path) -> None:
    write_file(dest, "2001", b"not a folder")
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert outcome(result, FIRST)[0] == STATUS_FAILED


# --- the manifest ---------------------------------------------------------------------


def test_when_every_manifest_name_is_taken_the_row_is_reported_not_logged(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    stamp = "20260101T000000Z"
    monkeypatch.setattr(manifest_module, "utc_stamp", lambda: stamp)
    monkeypatch.setattr(manifest_module, "MAX_NAME_ATTEMPTS", 2)
    write_file(dest, f"fastfoto-reorient-manifest-{stamp}.csv", b"one")
    write_file(dest, f"fastfoto-reorient-manifest-{stamp}-1.csv", b"two")
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_UNLOGGED}
    assert (dest / FIRST).is_file()
    assert "written but not in the manifest: 1" in format_fix(result, "dest")


def test_a_manifest_whose_header_cannot_be_written_is_not_left_open(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    real = manifest_module._write_all
    calls: list[int] = []

    def fail_first(fd: int, data: bytes) -> None:
        calls.append(fd)
        if len(calls) == 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        real(fd, data)

    monkeypatch.setattr(manifest_module, "_write_all", fail_first)
    result = apply_plan(two_rows(lib), lib, dest)
    assert statuses(result) == {FIRST: STATUS_UNLOGGED, SECOND: STATUS_WRITTEN}
    assert len(manifest_files(dest)) == 1  # the half-made one is removed; the next row made one
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(calls[0])
