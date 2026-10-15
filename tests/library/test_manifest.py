"""The manifest of a ``fix`` run: private, exclusive, unique per run, flushed row by row."""

import os
import re
from pathlib import Path

import pytest

from fastfoto_linux.library import manifest as manifest_module
from fastfoto_linux.library.apply import STATUS_UNLOGGED, STATUS_WRITTEN, apply_plan
from fastfoto_linux.library.summary import fix_problems
from tests.library.apply_helpers import FIRST, SECOND, THIRD, statuses, two_rows
from tests.library.jpeg_helpers import (
    manifest_files,
    manifest_rows,
    rotate_row,
    write_file,
)

OLD_FIXED_NAME = "fastfoto-reorient-manifest.csv"
UNIQUE_NAME = re.compile(r"fastfoto-reorient-manifest-\d{8}T\d{6}Z(-\d+)?\.csv")
HEADER = ["path", "old_tag", "new_tag"]


def test_each_run_writes_its_own_manifest_with_a_unique_name(lib: Path, dest: Path) -> None:
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    apply_plan([rotate_row(lib, SECOND, 90, 6, 3)], lib, dest)
    names = [path.name for path in manifest_files(dest)]
    assert len(names) == 2
    assert all(UNIQUE_NAME.fullmatch(name) for name in names)
    lengths = [len((dest / name).read_text(encoding="utf-8").splitlines()) for name in names]
    assert lengths == [2, 2]  # a header and one row each


def test_a_name_that_is_already_taken_gets_a_suffix_and_the_other_file_is_untouched(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    stamp = "20260101T000000Z"
    monkeypatch.setattr(manifest_module, "utc_stamp", lambda: stamp)
    taken = write_file(dest, f"fastfoto-reorient-manifest-{stamp}.csv", b"precious")
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert taken.read_bytes() == b"precious"
    assert len(manifest_files(dest)) == 2
    assert (dest / f"fastfoto-reorient-manifest-{stamp}-1.csv").is_file()


@pytest.mark.timeout(5)
@pytest.mark.parametrize("kind", ["symlink", "hard link", "fifo"])
def test_anything_planted_at_the_old_fixed_name_is_left_alone(
    kind: str, lib: Path, dest: Path, tmp_path: Path
) -> None:
    outside = write_file(tmp_path, "outside.txt", b"keep me")
    planted = dest / OLD_FIXED_NAME
    if kind == "symlink":
        planted.symlink_to(outside)
    elif kind == "hard link":
        os.link(outside, planted)
    else:
        os.mkfifo(planted)
    before = planted.lstat()
    result = apply_plan(two_rows(lib), lib, dest)
    assert set(statuses(result).values()) == {STATUS_WRITTEN}
    assert outside.read_bytes() == b"keep me"
    assert planted.lstat().st_ino == before.st_ino
    assert planted.lstat().st_mode == before.st_mode
    assert len(manifest_files(dest)) == 1


def test_a_name_with_a_newline_and_quotes_round_trips_through_the_csv(
    lib: Path, dest: Path
) -> None:
    awkward = 'say "hi",\nthere/photo_1,0_a.jpg'
    write_file(lib, awkward, (lib / FIRST).read_bytes())
    apply_plan([rotate_row(lib, awkward, 90, 1, 6)], lib, dest)
    assert manifest_rows(dest) == [HEADER, [awkward, "1", "6"]]


def test_the_manifest_is_private_and_flushed_after_every_row(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    real_fsync = os.fsync
    synced: list[int] = []

    def spy(fd: int) -> None:
        synced.append(os.fstat(fd).st_ino)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    apply_plan([*two_rows(lib), rotate_row(lib, THIRD, 90, 1, 6)], lib, dest)
    (path,) = manifest_files(dest)
    assert synced.count(path.stat().st_ino) >= 3  # once per row
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_manifest_that_cannot_be_written_is_reported_per_row_and_the_copies_stay(
    lib: Path, dest: Path
) -> None:
    (dest / "2001").mkdir()
    dest.chmod(0o500)  # the copies go into 2001, the manifest into the folder itself
    try:
        result = apply_plan(two_rows(lib), lib, dest)
    finally:
        dest.chmod(0o700)
    assert statuses(result) == {FIRST: STATUS_UNLOGGED, SECOND: STATUS_UNLOGGED}
    assert (dest / FIRST).is_file() and (dest / SECOND).is_file()
    lines = fix_problems(result)
    assert len(lines) == 2
    assert all("unlogged" in line for line in lines)
