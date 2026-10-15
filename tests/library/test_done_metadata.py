"""A run killed between linking a copy and giving it its mode and times is finished by the next.

The copy is linked while it is still private and has the time it was written; mode and times follow
through the open descriptor. If the process dies in between, the next run finds identical bytes
(``done``) and must still put the source's mode and times on the file.
"""

import os
import stat
from pathlib import Path

import pytest

from fastfoto_linux.library.apply import STATUS_DONE, STATUS_EXISTS, apply_plan
from tests.library.apply_helpers import FIRST, MTIME_NS, statuses
from tests.library.jpeg_helpers import rotate_row

SOURCE_MODE = 0o640
KILLED_MODE = 0o600
KILLED_NS = 1_700_000_000_000_000_000
LEFTOVER = ".trip_0001_a.jpg.0badcafe.tmp"


def killed_copy(lib: Path, dest: Path) -> Path:
    """The copy ``fix`` leaves if it dies after linking: right bytes, private mode, new times."""
    (lib / FIRST).chmod(SOURCE_MODE)
    os.utime(lib / FIRST, ns=(MTIME_NS, MTIME_NS))
    row = rotate_row(lib, FIRST, 90, 1, 6)
    assert statuses(apply_plan([row], lib, dest)) == {FIRST: "written"}
    copy = dest / FIRST
    copy.chmod(KILLED_MODE)
    os.utime(copy, ns=(KILLED_NS, KILLED_NS))
    return copy


def test_an_identical_copy_gets_the_sources_mode_and_times(lib: Path, dest: Path) -> None:
    copy = killed_copy(lib, dest)
    content = copy.read_bytes()
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_DONE}
    info = copy.stat()
    assert stat.S_IMODE(info.st_mode) == SOURCE_MODE
    assert info.st_mtime_ns == MTIME_NS
    assert copy.read_bytes() == content


def test_a_copy_that_already_has_them_is_left_as_it_is(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    killed_copy(lib, dest)
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)  # repairs it
    calls = []
    real = os.utime
    monkeypatch.setattr(
        os, "utime", lambda *args, **kwargs: calls.append(args) or real(*args, **kwargs)
    )
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_DONE}
    assert calls == []


def test_a_different_file_at_the_name_is_reported_and_its_mode_and_times_are_not_touched(
    lib: Path, dest: Path
) -> None:
    other = dest / FIRST
    other.parent.mkdir(parents=True)
    other.write_bytes(b"somebody else's file")
    other.chmod(KILLED_MODE)
    os.utime(other, ns=(KILLED_NS, KILLED_NS))
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_EXISTS}
    info = other.stat()
    assert (stat.S_IMODE(info.st_mode), info.st_mtime_ns) == (KILLED_MODE, KILLED_NS)


def test_a_leftover_staging_file_is_still_reported_and_kept(lib: Path, dest: Path) -> None:
    copy = killed_copy(lib, dest)
    leftover = copy.parent / LEFTOVER
    leftover.write_bytes(b"half a copy")
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_DONE}
    assert result.leftover_staging == 1
    assert leftover.read_bytes() == b"half a copy"
