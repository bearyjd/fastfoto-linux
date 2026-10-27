"""Seventh review pass: late fdopen failures, publishing by rename, a killed writer in a fresh
interpreter, and an ascent whose close is interrupted."""

import errno
import os
import signal
import subprocess
import sys

import pytest

from fastfoto_linux.evaluation import redeye_output
from fastfoto_linux.evaluation.redeye_images import fdopen_owned
from fastfoto_linux.evaluation.redeye_manifest import ManifestError
from fastfoto_linux.evaluation.redeye_output import write_outputs

BUNDLE = {"report.json": "R", "summary.md": "S", "perf.json": "P"}
_DIR = os.O_RDONLY | os.O_DIRECTORY
_KILLER = """
import os, signal, sys
from pathlib import Path
from fastfoto_linux.evaluation import redeye_output

redeye_output.PROJECT_NAME = "not-a-real-project"
real = os.open

def killing(path, *args, **kwargs):
    fd = real(path, *args, **kwargs)
    if str(path) == ".report.tmp":
        os.write(fd, b"{")
        os.kill(os.getpid(), signal.SIGKILL)
    return fd

redeye_output.os.open = killing
redeye_output.write_outputs(Path(sys.argv[1]), {"report.json": "R", "summary.md": "S"})
"""


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_a_late_fdopen_failure_closes_the_descriptor_once_and_raises_the_real_error(
    tmp_path,
) -> None:
    fd = os.open(tmp_path / "f", os.O_WRONLY | os.O_CREAT)
    before = _open_fds()
    with pytest.raises(LookupError):  # not EBADF from a second close
        fdopen_owned(fd, "w", encoding="no-such-encoding")
    assert _open_fds() == before - 1  # the wrapper closed it, exactly once


@pytest.mark.usefixtures("outside_checkout")
def test_publishing_does_not_need_hard_links(tmp_path, monkeypatch) -> None:
    def no_link(*args, **kwargs):
        raise OSError(errno.EPERM, "no hard links here")

    monkeypatch.setattr(redeye_output.os, "link", no_link)
    out = tmp_path / "out"
    name = write_outputs(out, BUNDLE)
    assert (out / name / "report.json").read_bytes() == b"R"
    assert sorted(p.name for p in (out / name).iterdir()) == sorted(BUNDLE)


def test_an_existing_report_json_is_never_replaced(tmp_path) -> None:
    (tmp_path / ".report.tmp").write_text("new")
    (tmp_path / "report.json").write_text("planted")
    fd = os.open(tmp_path, _DIR)
    try:
        with pytest.raises(ManifestError):
            redeye_output._publish_report(fd, [])
    finally:
        os.close(fd)
    assert (tmp_path / "report.json").read_text() == "planted"
    assert (tmp_path / ".report.tmp").read_text() == "new"


def test_a_writer_sigkilled_in_a_fresh_interpreter_leaves_no_report_json(tmp_path) -> None:
    out = tmp_path / "out"
    done = subprocess.run(
        [sys.executable, "-c", _KILLER, str(out)], timeout=60, capture_output=True, check=False
    )
    assert done.returncode == -signal.SIGKILL
    (run,) = (p for p in out.iterdir() if p.name.startswith("run-"))
    assert not (run / "report.json").exists()


def test_an_interrupted_close_during_the_ascent_leaks_nothing_and_does_not_fail_the_check(
    tmp_path, monkeypatch
) -> None:
    directory = tmp_path / "a" / "b"
    directory.mkdir(parents=True)
    fd = os.open(directory, _DIR)
    try:
        before = _open_fds()
        real, calls = os.close, []

        def interrupted(target):
            calls.append(target)
            real(target)
            if len(calls) == 1:  # released, then reported as interrupted
                raise InterruptedError(errno.EINTR, "injected")

        monkeypatch.setattr(redeye_output.os, "close", interrupted)
        redeye_output._refuse_if_contained(fd, frozenset())  # the close did release the fd
        monkeypatch.undo()
        assert len(calls) > 1
        assert _open_fds() == before
    finally:
        os.close(fd)


def test_a_report_json_that_cannot_be_looked_at_is_a_manifest_error(tmp_path, monkeypatch) -> None:
    (tmp_path / ".report.tmp").write_text("new")

    def failing(*args, **kwargs):
        raise OSError(errno.EIO, "injected")

    fd = os.open(tmp_path, _DIR)
    try:
        monkeypatch.setattr(redeye_output.os, "stat", failing)
        with pytest.raises(ManifestError):
            redeye_output._publish_report(fd, [])
        monkeypatch.undo()
    finally:
        os.close(fd)
    assert not (tmp_path / "report.json").exists()
