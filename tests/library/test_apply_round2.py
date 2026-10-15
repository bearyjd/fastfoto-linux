"""``fix`` details: mode and times, folder modes, placeholders, the manifest and leftovers."""

import errno
import os
import stat
from pathlib import Path

import pytest

from fastfoto_linux.cli.app import main
from fastfoto_linux.library import manifest as manifest_module
from fastfoto_linux.library.apply import (
    STATUS_EXISTS,
    STATUS_UNLOGGED,
    STATUS_WRITTEN,
    apply_plan,
)
from fastfoto_linux.library.plan import write_plan
from tests.library.apply_helpers import FIRST, SECOND, statuses, two_rows
from tests.library.jpeg_helpers import manifest_files, manifest_rows, rotate_row, write_file

PRIVATE = 0o600


def no_hard_links(*_args, **_kwargs) -> None:
    raise OSError(errno.EPERM, "this filesystem has no hard links")


def run_fix(tmp_path: Path, lib: Path, dest: Path, *extra: str) -> int:
    plan = tmp_path / "plan.csv"
    write_plan(plan, two_rows(lib))
    argv = ["library", "fix", str(plan), "--source", str(lib), "--out", str(dest), *extra]
    return main(argv)


# --- the copy is private until it has its place ---------------------------------------------------


def test_the_copy_is_still_private_when_it_is_linked_and_gets_mode_and_times_after(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    (lib / FIRST).chmod(0o640)
    row = rotate_row(lib, FIRST, 90, 1, 6)
    wanted = (lib / FIRST).stat()
    seen: list[tuple[int, int]] = []
    real_link = os.link

    def spy(src, dst, *, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        info = os.stat(src, dir_fd=src_dir_fd)
        seen.append((stat.S_IMODE(info.st_mode), info.st_mtime_ns))
        real_link(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )

    monkeypatch.setattr(os, "link", spy)
    apply_plan([row], lib, dest)
    assert seen
    assert all(mode == PRIVATE for mode, _ in seen)
    assert all(mtime != wanted.st_mtime_ns for _, mtime in seen)
    final = (dest / FIRST).stat()
    assert stat.S_IMODE(final.st_mode) == 0o640
    assert final.st_mtime_ns == wanted.st_mtime_ns


def test_a_copy_whose_mode_cannot_be_set_after_publishing_is_taken_back(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    def broken(*_args, **_kwargs) -> None:
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(os, "utime", broken)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: "failed"}
    assert not (dest / FIRST).exists()


# --- new folders take the mode of the source folder -----------------------------------------------


def test_new_destination_folders_get_the_mode_of_the_source_folder(lib: Path, dest: Path) -> None:
    (lib / "2001").chmod(0o750)
    previous = os.umask(0o077)
    try:
        apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    finally:
        os.umask(previous)
    assert stat.S_IMODE((dest / "2001").stat().st_mode) == 0o750


def test_a_read_only_source_folder_still_gets_a_destination_folder_we_can_write_to(
    lib: Path, dest: Path
) -> None:
    (lib / "2001").chmod(0o555)
    try:
        result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    finally:
        (lib / "2001").chmod(0o755)
    assert statuses(result) == {FIRST: STATUS_WRITTEN}
    assert stat.S_IMODE((dest / "2001").stat().st_mode) == 0o755


def test_a_destination_made_by_mkdir_gets_the_mode_of_the_library_folder(
    tmp_path: Path, lib: Path
) -> None:
    lib.chmod(0o750)
    dest = tmp_path / "made" / "dest"
    previous = os.umask(0o077)
    try:
        assert run_fix(tmp_path, lib, dest, "--mkdir") == 0
    finally:
        os.umask(previous)
    assert stat.S_IMODE(dest.stat().st_mode) == 0o750


def test_an_existing_destination_folder_keeps_its_mode(lib: Path, dest: Path) -> None:
    (dest / "2001").mkdir()
    (dest / "2001").chmod(0o700)
    (lib / "2001").chmod(0o755)
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert stat.S_IMODE((dest / "2001").stat().st_mode) == 0o700


# --- filesystems without hard links ---------------------------------------------------------------


def test_an_empty_placeholder_left_by_a_crash_is_replaced_on_a_filesystem_without_links(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    monkeypatch.setattr(os, "link", no_hard_links)
    write_file(dest, FIRST, b"")
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_WRITTEN}
    assert (dest / FIRST).stat().st_size > 0


def test_anything_else_at_the_name_is_not_a_placeholder(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(os, "link", no_hard_links)
    write_file(dest, FIRST, b"someone's own file")
    (dest / SECOND).symlink_to(tmp_path / "never-created")
    result = apply_plan(two_rows(lib), lib, dest)
    assert statuses(result) == {FIRST: STATUS_EXISTS, SECOND: STATUS_EXISTS}
    assert (dest / FIRST).read_bytes() == b"someone's own file"
    assert not (tmp_path / "never-created").exists()


# --- the manifest ---------------------------------------------------------------------------------


def test_a_manifest_whose_header_cannot_be_written_leaves_no_empty_file_behind(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    real = manifest_module._write_all
    calls: list[int] = []

    def fail_first(fd: int, data: bytes) -> None:
        calls.append(fd)
        if len(calls) == 1:
            raise OSError(errno.ENOSPC, "no space left on device")
        real(fd, data)

    monkeypatch.setattr(manifest_module, "_write_all", fail_first)
    result = apply_plan(two_rows(lib), lib, dest)
    assert statuses(result) == {FIRST: STATUS_UNLOGGED, SECOND: STATUS_WRITTEN}
    (only,) = manifest_files(dest)
    assert only.stat().st_size > 0
    assert [row[0] for row in manifest_rows(dest)] == ["path", SECOND]


# --- leftovers of a killed run --------------------------------------------------------------------


def test_staging_files_left_by_a_killed_run_are_counted_and_not_deleted(
    tmp_path: Path, lib: Path, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    leftovers = [dest / ".b.jpg.0123abcd.tmp", dest / "2001" / ".trip_0001_a.jpg.deadbeef.tmp"]
    for path in leftovers:
        write_file(dest, path.relative_to(dest).as_posix(), b"half a photo")
    write_file(dest, "2001/notes.tmp", b"not ours")
    assert run_fix(tmp_path, lib, dest) == 0
    assert "leftover staging files: 2" in capsys.readouterr().out
    assert all(path.read_bytes() == b"half a photo" for path in leftovers)


def test_a_clean_run_does_not_mention_leftovers(
    tmp_path: Path, lib: Path, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_fix(tmp_path, lib, dest) == 0
    assert "leftover" not in capsys.readouterr().out
