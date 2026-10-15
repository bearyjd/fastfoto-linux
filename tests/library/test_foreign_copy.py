"""An identical file in DEST that is not ours is done, with a note; a refusal says what it did.

Only the owner (or root) may change a file's mode and times, so ``fix`` does not try on a file
that another user owns: it leaves it exactly as it is. The content is verified identical, so the row
is ``done`` (a run could never do better) and the note says the file was left alone; the
"destination does not accept permissions" warning (meant for filesystems without them) is not
printed for it. When the system refuses a change on our own file, the row says which of the mode
and the times it did and did not get to apply.
"""

import errno
import logging
import os
import stat
from pathlib import Path

import pytest

from fastfoto_linux.library import fdio
from fastfoto_linux.library.apply import STATUS_DONE, STATUS_EXISTS, STATUS_WRITTEN, apply_plan
from tests.library.apply_helpers import FIRST, statuses
from tests.library.jpeg_helpers import rotate_row

OTHER_MODE = 0o600
OTHER_NS = 1_700_000_000_000_000_000
NOT_OURS_NOTE = (
    "already there (owned by another user; its permissions and times were left as they are)"
)


def refuse(*_args: object, **_kwargs: object) -> None:
    raise PermissionError(errno.EPERM, "Operation not permitted")


def identical_copy(lib: Path, dest: Path) -> Path:
    """A copy of the first photo in ``dest`` whose mode and times are not the source's."""
    assert statuses(apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)) == {
        FIRST: STATUS_WRITTEN
    }
    copy = dest / FIRST
    copy.chmod(OTHER_MODE)
    os.utime(copy, ns=(OTHER_NS, OTHER_NS))
    return copy


def owned_by_someone_else(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every file look foreign: the effective user is no longer the one who owns them."""
    real = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: real + 1)


def metadata(path: Path) -> tuple[int, int]:
    info = path.stat()
    return stat.S_IMODE(info.st_mode), info.st_mtime_ns


def test_an_identical_file_that_another_user_owns_is_done_with_a_note(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, lib: Path, dest: Path
) -> None:
    copy = identical_copy(lib, dest)
    content = copy.read_bytes()
    owned_by_someone_else(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(os, "fchmod", lambda *a, **k: calls.append("fchmod") or refuse())
    monkeypatch.setattr(os, "utime", lambda *a, **k: calls.append("utime") or refuse())
    fdio._warn_modes_unsupported.cache_clear()
    with caplog.at_level(logging.WARNING, logger=fdio.logger.name):
        result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_DONE}
    assert [outcome.reason for outcome in result.outcomes] == [NOT_OURS_NOTE]
    assert calls == []  # the mode and times were not even tried
    assert [r for r in caplog.records if "does not accept" in r.getMessage()] == []
    assert metadata(copy) == (OTHER_MODE, OTHER_NS)
    assert copy.read_bytes() == content


def test_a_refused_change_of_times_after_the_mode_was_set_says_so(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    """Our own file, but the system refuses the times (an append-only file, a squashing mount)."""
    copy = identical_copy(lib, dest)
    monkeypatch.setattr(os, "utime", refuse)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_EXISTS}
    reason = result.outcomes[0].reason
    assert "permissions now match the source's" in reason
    assert "times could not be set" in reason
    assert "Operation not permitted" in reason
    assert "untouched" not in reason
    assert metadata(copy) == (
        stat.S_IMODE((lib / FIRST).stat().st_mode),
        OTHER_NS,
    )  # mode did change


def test_a_refused_change_of_both_says_neither_was_applied(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    copy = identical_copy(lib, dest)
    monkeypatch.setattr(os, "fchmod", refuse)
    monkeypatch.setattr(os, "utime", refuse)
    fdio._warn_modes_unsupported.cache_clear()
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_EXISTS}
    reason = result.outcomes[0].reason
    assert "permissions could not be set" in reason
    assert "times could not be set" in reason
    assert metadata(copy) == (OTHER_MODE, OTHER_NS)


def test_a_foreign_file_that_already_has_the_right_mode_and_times_is_done(
    monkeypatch: pytest.MonkeyPatch, lib: Path, dest: Path
) -> None:
    """Nothing needs changing, so ownership does not matter."""
    assert statuses(apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)) == {
        FIRST: STATUS_WRITTEN
    }
    owned_by_someone_else(monkeypatch)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_DONE}


def test_a_file_we_own_still_gets_the_sources_mode_and_times(lib: Path, dest: Path) -> None:
    copy = identical_copy(lib, dest)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert statuses(result) == {FIRST: STATUS_DONE}
    assert metadata(copy) == (
        stat.S_IMODE((lib / FIRST).stat().st_mode),
        (lib / FIRST).stat().st_mtime_ns,
    )
