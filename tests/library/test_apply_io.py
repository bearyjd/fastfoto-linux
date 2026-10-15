"""How ``fix`` reads and writes: through open descriptors, never through a path that can change."""

import errno
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.library import apply as apply_module
from fastfoto_linux.library import fdio, safety
from fastfoto_linux.library.apply import (
    REASON_UNSAFE_DESTINATION,
    STATUS_DONE,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_STALE,
    STATUS_WRITTEN,
    apply_plan,
)
from fastfoto_linux.library.jpeg_exif import read_orientation
from tests.library.apply_helpers import FIRST, SECOND, statuses, two_rows
from tests.library.jpeg_helpers import manifest_files, rotate_row, tree_snapshot, write_file


def outcome(result, path: str) -> tuple[str, str]:
    (found,) = [o for o in result.outcomes if o.path == path]
    return found.status, found.reason


# --- reading --------------------------------------------------------------------------


@pytest.mark.timeout(5)
def test_a_fifo_standing_in_for_a_photo_is_stale_and_never_opened_blocking(
    lib: Path, dest: Path
) -> None:
    row = rotate_row(lib, FIRST, 90, 1, 6)
    (lib / FIRST).unlink()
    os.mkfifo(lib / FIRST)
    assert statuses(apply_plan([row], lib, dest)) == {FIRST: STATUS_STALE}


def test_a_file_over_the_size_cap_is_stale_and_not_read(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    row = rotate_row(lib, FIRST, 90, 1, 6)
    monkeypatch.setattr(fdio, "MAX_FILE_BYTES", row.size - 1)
    assert statuses(apply_plan([row], lib, dest)) == {FIRST: STATUS_STALE}
    assert not (dest / FIRST).exists()


# --- writing --------------------------------------------------------------------------


def test_a_folder_swapped_for_a_link_into_the_library_after_validation_is_refused(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    (lib / "elsewhere").mkdir()
    (dest / "2001").mkdir()
    real_edit = apply_module.set_orientation

    def swap_then_edit(data: bytes, tag: int) -> bytes:
        (dest / "2001").rmdir()
        (dest / "2001").symlink_to(lib / "elsewhere", target_is_directory=True)
        return real_edit(data, tag)

    monkeypatch.setattr(apply_module, "set_orientation", swap_then_edit)
    before = tree_snapshot(lib)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert outcome(result, FIRST) == (STATUS_FAILED, REASON_UNSAFE_DESTINATION)
    assert tree_snapshot(lib) == before


def test_a_destination_folder_that_is_the_library_by_identity_is_refused(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    (dest / "2001").mkdir()
    pair = {lib.stat().st_ino, (dest / "2001").stat().st_ino}
    real = safety.same_directory
    monkeypatch.setattr(
        safety, "same_directory", lambda a, b: real(a, b) or {a.st_ino, b.st_ino} == pair
    )
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert outcome(result, FIRST) == (STATUS_FAILED, REASON_UNSAFE_DESTINATION)
    assert not any((dest / "2001").iterdir())


def test_setuid_and_setgid_bits_are_not_copied(lib: Path, dest: Path) -> None:
    (lib / FIRST).chmod(0o4755)
    (lib / SECOND).chmod(0o2755)
    apply_plan(two_rows(lib), lib, dest)
    for name in (FIRST, SECOND):
        assert stat.S_IMODE((dest / name).stat().st_mode) == 0o755


def test_modes_and_both_times_are_copied_from_the_source(lib: Path, dest: Path) -> None:
    os.utime(lib / FIRST, ns=(1_000_000_000_111_111_111, 1_100_000_000_222_222_222))
    (lib / FIRST).chmod(0o640)
    before = (lib / FIRST).stat()
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    after = (dest / FIRST).stat()
    assert (after.st_atime_ns, after.st_mtime_ns) == (before.st_atime_ns, before.st_mtime_ns)
    assert stat.S_IMODE(after.st_mode) == 0o640


def test_extended_attributes_are_not_copied(lib: Path, dest: Path) -> None:
    try:
        os.setxattr(lib / FIRST, "user.fastfoto-test", b"1")
    except OSError:
        pytest.skip("this filesystem has no user extended attributes")
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert os.listxattr(dest / FIRST) == []


def test_the_staging_file_is_created_private_exclusive_and_without_following_links(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    real_open = os.open
    calls: list[tuple[str, int, int]] = []

    def spy(path, flags, mode=0o777, *, dir_fd=None):
        calls.append((os.fsdecode(path), flags, mode))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    previous = os.umask(0)  # so that only the requested mode can be seen
    try:
        monkeypatch.setattr(os, "open", spy)
        apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    finally:
        os.umask(previous)
    staging = [c for c in calls if c[0].startswith(".") and c[0].endswith(".tmp")]
    assert staging
    for _, flags, mode in staging:
        assert mode == 0o600
        assert flags & os.O_EXCL and flags & os.O_NOFOLLOW and flags & os.O_CREAT


def test_a_filesystem_without_hard_links_still_gets_the_copies(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    def no_links(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    write_file(dest, SECOND, b"precious")
    result = apply_plan(two_rows(lib), lib, dest)
    assert statuses(result) == {FIRST: STATUS_WRITTEN, SECOND: STATUS_EXISTS}
    assert read_orientation((dest / FIRST).read_bytes()) == 6
    assert (dest / SECOND).read_bytes() == b"precious"
    leftovers = [p.name for p in dest.rglob("*") if p.name.endswith(".tmp")]
    assert leftovers == []


# --- running again --------------------------------------------------------------------


def test_a_second_run_counts_identical_copies_as_done_and_writes_no_second_manifest(
    lib: Path, dest: Path
) -> None:
    rows = two_rows(lib)
    apply_plan(rows, lib, dest)
    second = apply_plan(rows, lib, dest)
    assert statuses(second) == {FIRST: STATUS_DONE, SECOND: STATUS_DONE}
    assert second.count(STATUS_DONE) == 2
    assert len(manifest_files(dest)) == 1


def test_an_interrupted_run_is_finished_by_the_next_one(lib: Path, dest: Path) -> None:
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    result = apply_plan(two_rows(lib), lib, dest)
    assert statuses(result) == {FIRST: STATUS_DONE, SECOND: STATUS_WRITTEN}


def test_an_existing_file_that_differs_is_still_reported_as_existing(lib: Path, dest: Path) -> None:
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    expected = (dest / FIRST).read_bytes()
    (dest / FIRST).write_bytes(expected[:-1] + bytes([expected[-1] ^ 0xFF]))  # same length
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_EXISTS}


def test_a_link_to_the_right_bytes_is_not_followed_and_not_counted_as_done(
    lib: Path, dest: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, other)
    (dest / "2001").mkdir()
    (dest / FIRST).symlink_to(other / FIRST)
    row = replace(rotate_row(lib, FIRST, 90, 1, 6))
    assert statuses(apply_plan([row], lib, dest)) == {FIRST: STATUS_EXISTS}
