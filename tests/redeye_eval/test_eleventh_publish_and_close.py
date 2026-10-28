"""Eleventh review pass: an interrupted publication never leaves a ``report.json`` behind, and
a close failure of any kind never replaces the failure already being raised."""

import errno
import os

import pytest

from fastfoto_linux.evaluation import redeye_output
from fastfoto_linux.evaluation.redeye_manifest import ManifestError
from fastfoto_linux.evaluation.redeye_output import write_outputs

BUNDLE = {"report.json": "R" * 50, "summary.md": "S" * 50, "perf.json": "P" * 50}
_INTERRUPTIONS = {"interrupt": KeyboardInterrupt, "memory": MemoryError, "exit": SystemExit}


@pytest.fixture(autouse=True)
def _outside(outside_checkout):
    return None


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


def _run(out, monkeypatch=None):
    try:
        return None, write_outputs(out, BUNDLE)
    except BaseException as error:  # KeyboardInterrupt and SystemExit are under test
        return error, ""


@pytest.mark.parametrize("kind", _INTERRUPTIONS)
def test_interruption_just_after_the_real_rename_leaves_no_report(tmp_path, monkeypatch, kind):
    out, real_rename = tmp_path / "out", os.rename
    injected = _INTERRUPTIONS[kind]()

    def rename_then_raise(*args, **kwargs):
        real_rename(*args, **kwargs)
        raise injected

    before = _open_fds()
    monkeypatch.setattr(os, "rename", rename_then_raise)
    outcome, _ = _run(out)
    monkeypatch.undo()
    assert outcome is injected
    assert not list(out.rglob("report.json"))
    assert list(out.iterdir()) == []  # the run directory went too
    assert _open_fds() == before


@pytest.mark.parametrize("kind", _INTERRUPTIONS)
def test_interruption_between_rename_and_directory_fsync_leaves_no_report(
    tmp_path, monkeypatch, kind
):
    out, real_fsync, calls = tmp_path / "out", os.fsync, []
    injected = _INTERRUPTIONS[kind]()

    def fsync(fd):
        calls.append(fd)
        if len(calls) == len(BUNDLE) + 1:  # three files, then the directory
            raise injected
        real_fsync(fd)

    before = _open_fds()
    monkeypatch.setattr(os, "fsync", fsync)
    outcome, _ = _run(out)
    monkeypatch.undo()
    assert outcome is injected
    assert list(out.iterdir()) == []
    assert _open_fds() == before


@pytest.mark.parametrize("kind", _INTERRUPTIONS)
def test_interruption_before_the_rename_removes_the_temp_file(tmp_path, monkeypatch, kind):
    out = tmp_path / "out"
    injected = _INTERRUPTIONS[kind]()

    def rename(*args, **kwargs):
        raise injected

    before = _open_fds()
    monkeypatch.setattr(os, "rename", rename)
    outcome, _ = _run(out)
    monkeypatch.undo()
    assert outcome is injected
    assert list(out.iterdir()) == []  # neither .report.tmp nor report.json
    assert _open_fds() == before


class _Closes:
    """Records closes of the two directory descriptors; the chosen ones close for real and
    then raise ``failure``."""

    def __init__(self, monkeypatch, targets, failure) -> None:
        self.mine: dict[str, int] = {}
        self.closed: list[int] = []
        self.failures: list[BaseException] = []
        real_open_out, real_new_run = redeye_output._open_out_dir, redeye_output._new_run_dir
        real_close = os.close

        def open_out(*args):
            self.mine["out"] = real_open_out(*args)
            return self.mine["out"]

        def new_run(out_fd):
            name, fd = real_new_run(out_fd)
            self.mine["run"] = fd
            return name, fd

        def close(fd):
            real_close(fd)
            if fd in self.mine.values():
                self.closed.append(fd)
                if any(self.mine.get(t) == fd for t in targets):
                    self.failures.append(failure())
                    raise self.failures[-1]

        monkeypatch.setattr(redeye_output, "_open_out_dir", open_out)
        monkeypatch.setattr(redeye_output, "_new_run_dir", new_run)
        monkeypatch.setattr(os, "close", close)

    def assert_each_closed_once(self) -> None:
        assert set(self.mine) == {"out", "run"}
        for fd in self.mine.values():
            assert self.closed.count(fd) == 1


_FIRST_FAILURES = {
    "exit": lambda: SystemExit(73),
    "interrupt": KeyboardInterrupt,
    "memory": MemoryError,
    "oserror": lambda: OSError(errno.ENOSPC, "injected"),
}
_CLOSE_FAILURES = {"interrupt": KeyboardInterrupt, "memory": MemoryError, "exit": SystemExit}
_TARGETS = [("run",), ("out",), ("run", "out")]


@pytest.mark.parametrize("failure", _CLOSE_FAILURES)
@pytest.mark.parametrize("targets", _TARGETS, ids="+".join)
@pytest.mark.parametrize("first", _FIRST_FAILURES)
def test_the_original_failure_wins_over_any_close_failure(
    tmp_path, monkeypatch, first, targets, failure
):
    out, original = tmp_path / "out", _FIRST_FAILURES[first]()

    def write(fd, data):
        raise original

    before = _open_fds()
    closes = _Closes(monkeypatch, targets, _CLOSE_FAILURES[failure])
    monkeypatch.setattr(os, "write", write)
    outcome, _ = _run(out)
    monkeypatch.undo()
    if isinstance(original, OSError):
        assert isinstance(outcome, ManifestError)
        assert outcome.__cause__ is original
    else:
        assert outcome is original
    assert list(out.iterdir()) == []
    closes.assert_each_closed_once()
    assert _open_fds() == before


@pytest.mark.parametrize("failure", _CLOSE_FAILURES)
@pytest.mark.parametrize("target", ["run", "out"])
def test_a_non_oserror_close_failure_after_success_propagates_unchanged(
    tmp_path, monkeypatch, target, failure
):
    out = tmp_path / "out"
    before = _open_fds()
    closes = _Closes(monkeypatch, (target,), _CLOSE_FAILURES[failure])
    outcome, _ = _run(out)
    monkeypatch.undo()
    assert outcome is closes.failures[0]
    (run,) = list(out.iterdir())  # nothing else is propagating: the complete bundle is kept
    for file, text in BUNDLE.items():
        assert (run / file).read_bytes() == text.encode()
    closes.assert_each_closed_once()
    assert _open_fds() == before


@pytest.mark.parametrize("target", ["run", "out"])
def test_an_oserror_close_failure_after_success_is_a_manifest_error_and_keeps_the_bundle(
    tmp_path, monkeypatch, target
):
    out = tmp_path / "out"
    before = _open_fds()
    closes = _Closes(monkeypatch, (target,), lambda: OSError(errno.EIO, "injected"))
    outcome, _ = _run(out)
    monkeypatch.undo()
    assert isinstance(outcome, ManifestError)
    assert outcome.__cause__ is closes.failures[0]
    assert len(list((next(out.iterdir())).iterdir())) == len(BUNDLE)
    closes.assert_each_closed_once()
    assert _open_fds() == before
