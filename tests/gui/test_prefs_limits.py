"""The settings file is opened carefully: a regular file of bounded size, never a link or a pipe."""

import logging
import os
import signal
from collections.abc import Iterator
from pathlib import Path

import pytest

from fastfoto_linux.gui import prefs
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.state import Mode

HANG_GUARD_S = 5


@pytest.fixture
def hang_guard() -> Iterator[None]:
    """Fail the test, instead of hanging it, if the loader blocks (a FIFO with no writer)."""

    def alarm(signum: int, frame: object) -> None:
        pytest.fail("the settings loader blocked on the file")

    previous = signal.signal(signal.SIGALRM, alarm)
    signal.alarm(HANG_GUARD_S)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_the_size_cap_is_one_mebibyte() -> None:
    assert prefs.MAX_PREFS_BYTES == 1 << 20


def test_a_pipe_is_ignored_not_waited_for(tmp_path: Path, hang_guard: None) -> None:
    fifo = tmp_path / "gui.json"
    os.mkfifo(fifo)
    assert prefs.load_mode(fifo) is Mode.PHOTOS
    assert prefs.load_form(fifo) == ScanForm()


def test_a_symbolic_link_is_ignored(tmp_path: Path, hang_guard: None) -> None:
    target = tmp_path / "real.json"
    prefs.save_mode(Mode.DOCUMENTS, target)
    assert prefs.load_mode(target) is Mode.DOCUMENTS
    link = tmp_path / "gui.json"
    link.symlink_to(target)
    assert prefs.load_mode(link) is Mode.PHOTOS


def test_a_folder_is_ignored(tmp_path: Path, hang_guard: None) -> None:
    assert prefs.load_mode(tmp_path) is Mode.PHOTOS


def test_the_refusals_log_no_path(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    link = tmp_path / "gui.json"
    link.symlink_to(tmp_path / "real.json")
    (tmp_path / "big.json").write_bytes(b" " * (prefs.MAX_PREFS_BYTES + 1))
    with caplog.at_level(logging.WARNING, logger=prefs.__name__):
        prefs.load_mode(link)
        prefs.load_mode(tmp_path / "big.json")
        prefs.load_mode(tmp_path)
    assert caplog.records
    assert str(tmp_path) not in caplog.text
