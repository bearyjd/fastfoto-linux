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


def test_a_pipe_is_refused_not_waited_for(
    tmp_path: Path, hang_guard: None, caplog: pytest.LogCaptureFixture
) -> None:
    fifo = tmp_path / "gui.json"
    os.mkfifo(fifo)
    with caplog.at_level(logging.WARNING, logger=prefs.__name__):
        assert prefs.load_mode(fifo) is Mode.PHOTOS
        assert prefs.load_form(fifo) == ScanForm()
    assert "not a regular file" in caplog.text


def test_a_device_behind_a_link_is_refused(
    tmp_path: Path, hang_guard: None, caplog: pytest.LogCaptureFixture
) -> None:
    link = tmp_path / "gui.json"
    link.symlink_to("/dev/zero")
    with caplog.at_level(logging.WARNING, logger=prefs.__name__):
        assert prefs.load_form(link) == ScanForm()
    assert "not a regular file" in caplog.text


def test_a_link_to_a_regular_settings_file_is_read(tmp_path: Path) -> None:
    target = tmp_path / "dotfiles" / "gui.json"
    target.parent.mkdir()
    prefs.save_mode(Mode.DOCUMENTS, target)
    link = tmp_path / "gui.json"
    link.symlink_to(target)
    assert prefs.load_mode(link) is Mode.DOCUMENTS


def test_a_dangling_or_looping_link_gives_the_defaults(tmp_path: Path, hang_guard: None) -> None:
    dangling = tmp_path / "dangling.json"
    dangling.symlink_to(tmp_path / "missing.json")
    loop = tmp_path / "loop.json"
    loop.symlink_to(loop)
    for path in (dangling, loop):
        assert prefs.load_mode(path) is Mode.PHOTOS
        assert prefs.load_form(path) == ScanForm()


def test_a_folder_is_ignored(tmp_path: Path, hang_guard: None) -> None:
    assert prefs.load_mode(tmp_path) is Mode.PHOTOS


def test_the_refusals_log_no_path(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    link = tmp_path / "gui.json"
    link.symlink_to(tmp_path / "loop.json")
    (tmp_path / "loop.json").symlink_to(link)
    (tmp_path / "big.json").write_bytes(b" " * (prefs.MAX_PREFS_BYTES + 1))
    with caplog.at_level(logging.WARNING, logger=prefs.__name__):
        prefs.load_mode(link)
        prefs.load_mode(tmp_path / "big.json")
        prefs.load_mode(tmp_path)
    assert caplog.records
    assert str(tmp_path) not in caplog.text
