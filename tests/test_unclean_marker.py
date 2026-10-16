"""The note "our own last scan on this USB address ended abnormally", kept in the state folder.

It is the evidence that lets the pre-scan check send filler to a scanner that stays silent: no
note, no filler, because the silence may be another device's session (over Wi-Fi, say).
"""

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fastfoto_linux.scanner import unclean

LOGGER = "fastfoto_linux.scanner.unclean"
WHEN = datetime(2026, 10, 15, 12, 34, 56, tzinfo=UTC)


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    folder = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(folder))
    return folder


# --- where it lives ----------------------------------------------------------------------------


def test_it_lives_in_the_xdg_state_folder(state: Path) -> None:
    assert unclean.marker_path() == state / "fastfoto-linux" / "scanner-unclean"


@pytest.mark.parametrize("value", [None, "", "relative/state"], ids=["unset", "empty", "relative"])
def test_without_a_usable_xdg_state_home_it_is_under_dot_local_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    if value is None:
        monkeypatch.delenv("XDG_STATE_HOME")
    else:
        monkeypatch.setenv("XDG_STATE_HOME", value)  # the XDG rule: a relative path is ignored

    expected = tmp_path / ".local" / "state" / "fastfoto-linux" / "scanner-unclean"
    assert unclean.marker_path() == expected


# --- writing it --------------------------------------------------------------------------------


def test_it_says_which_address_and_when_in_utc(state: Path) -> None:
    unclean.mark(1, 4, now=WHEN)

    assert unclean.marker_path().read_text() == "001:004 2026-10-15T12:34:56Z\n"


def test_the_time_defaults_to_now(state: Path) -> None:
    unclean.mark(12, 3)

    assert re.fullmatch(
        r"012:003 [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\n",
        unclean.marker_path().read_text(),
    )


def test_a_new_note_replaces_the_old_one(state: Path) -> None:
    unclean.mark(1, 4, now=WHEN)
    unclean.mark(2, 9, now=WHEN)

    assert unclean.is_marked(2, 9)
    assert not unclean.is_marked(1, 4)


def test_it_is_written_atomically_and_leaves_nothing_else_behind(state: Path) -> None:
    unclean.mark(1, 4, now=WHEN)
    unclean.mark(1, 4, now=WHEN)

    assert sorted(p.name for p in unclean.marker_path().parent.iterdir()) == ["scanner-unclean"]


def test_a_write_that_fails_half_way_keeps_the_old_note_and_leaves_no_litter(
    state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unclean.mark(1, 4, now=WHEN)

    def refuse(*args: object) -> None:
        raise OSError("disk trouble")

    monkeypatch.setattr(os, "replace", refuse)
    unclean.mark(2, 9, now=WHEN)  # must not raise

    assert unclean.is_marked(1, 4)
    assert sorted(p.name for p in unclean.marker_path().parent.iterdir()) == ["scanner-unclean"]


def test_failing_to_write_it_never_raises_it_only_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """It is written while a scan error is on its way: it must not replace that error."""
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker / "state"))
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    unclean.mark(1, 4, now=WHEN)

    assert not unclean.is_marked(1, 4)
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


# --- reading it --------------------------------------------------------------------------------


def test_it_matches_only_the_address_it_names(state: Path) -> None:
    unclean.mark(1, 4, now=WHEN)

    assert unclean.is_marked(1, 4)
    assert not unclean.is_marked(1, 5)
    assert not unclean.is_marked(2, 4)
    assert not unclean.is_marked(4, 1)


def test_without_a_note_nothing_is_marked(state: Path) -> None:
    assert not unclean.is_marked(1, 4)


@pytest.mark.parametrize(
    "content",
    [b"", b"garbage\n", b"001:004:005 now\n", b"\xff\xfe\x00", b"1:4\n", b"0001:004 x\n"],
    ids=["empty", "garbage", "three-parts", "binary", "unpadded", "four-digits"],
)
def test_a_note_that_cannot_be_read_is_no_evidence(state: Path, content: bytes) -> None:
    unclean.marker_path().parent.mkdir(parents=True)
    unclean.marker_path().write_bytes(content)

    assert not unclean.is_marked(1, 4)


def test_a_note_that_is_not_a_file_is_no_evidence(state: Path) -> None:
    unclean.marker_path().mkdir(parents=True)

    assert not unclean.is_marked(1, 4)


# --- clearing it -------------------------------------------------------------------------------


def test_clearing_removes_it(state: Path) -> None:
    unclean.mark(1, 4, now=WHEN)

    unclean.clear()

    assert not unclean.marker_path().exists()
    assert not unclean.is_marked(1, 4)


def test_clearing_when_there_is_nothing_to_clear_is_fine(state: Path) -> None:
    unclean.clear()
    unclean.clear()


def test_failing_to_clear_it_never_raises(state: Path, caplog: pytest.LogCaptureFixture) -> None:
    unclean.marker_path().mkdir(parents=True)  # a folder cannot be unlinked as a file
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    unclean.clear()

    assert caplog.records
