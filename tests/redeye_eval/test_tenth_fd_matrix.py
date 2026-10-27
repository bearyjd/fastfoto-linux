"""Tenth review pass: write_outputs gives every descriptor its own try/finally, so closing one
never depends on an earlier cleanup step having succeeded. One matrix over (first failure) x
(cleanup failure) x (directory close failure); every cell checks the same invariants."""

import errno
import os

import pytest

from fastfoto_linux.evaluation import redeye_output
from fastfoto_linux.evaluation.redeye_manifest import ManifestError
from fastfoto_linux.evaluation.redeye_output import write_outputs

BUNDLE = {"report.json": "R" * 50, "summary.md": "S" * 50, "perf.json": "P" * 50}


@pytest.fixture(autouse=True)
def _outside(outside_checkout):
    return None


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


_POINTS = [None, "write", "fsync", "contain", "rename"]
# What the first failure raises; OSError/ValueError become ManifestError, the rest pass through.
_ORIGINALS = {
    "oserror": lambda: OSError(errno.ENOSPC, "injected"),
    "memory": MemoryError,
    "interrupt": KeyboardInterrupt,
}
_CLEANUPS = {
    "none": None,
    "unlink-memory": ("unlink", MemoryError),
    "unlink-interrupt": ("unlink", KeyboardInterrupt),
    "unlink-exit": ("unlink", SystemExit),
    "rmdir-oserror": ("rmdir", lambda: OSError(errno.EBUSY, "injected")),
    "rmdir-memory": ("rmdir", MemoryError),
}
_CLOSES = [(), ("run",), ("out",), ("run", "out")]


def _cells():
    for close in _CLOSES:
        yield pytest.param(
            (None, "none", "none", close), id=f"success-close-{'+'.join(close) or 'ok'}"
        )
    for point in _POINTS[1:]:
        for original in _ORIGINALS:
            for cleanup in _CLEANUPS:
                for close in _CLOSES:
                    cell = f"{point}-{original}-{cleanup}-close-{'+'.join(close) or 'ok'}"
                    yield pytest.param((point, original, cleanup, close), id=cell)


class _Harness:
    """Injects the first failure, the cleanup failure and the close failures; records closes."""

    def __init__(self, monkeypatch, point, original, cleanup, close) -> None:
        self.mine: dict[str, int] = {}
        self.closed: list[int] = []
        self.zero: int | None = None
        self.original = _ORIGINALS[original]() if point else None
        self.armed = False
        self._point, self._cleanup, self._close = point, _CLEANUPS[cleanup], close
        self._patch(monkeypatch)

    def _fire(self) -> None:
        self.armed = True
        raise self.original

    def _patch(self, monkeypatch) -> None:
        real_open_out, real_new_run = redeye_output._open_out_dir, redeye_output._new_run_dir
        real_contained = redeye_output._refuse_if_contained
        real = {n: getattr(os, n) for n in ("write", "fsync", "rename", "unlink", "rmdir", "close")}
        seen = {"write": 0, "fsync": 0}

        def open_out(*args):
            self.mine["out"] = real_open_out(*args)
            return self.mine["out"]

        def new_run(out_fd):
            name, fd = real_new_run(out_fd)
            self.mine["run"] = fd
            return name, fd

        def contained(fd, forbidden):
            real_contained(fd, forbidden)
            if self._point == "contain" and fd == self.mine.get("run"):
                self._fire()

        def counted(kind):
            def call(*args, **kwargs):
                seen[kind] += 1
                if self._point == kind and seen[kind] == 1:
                    self._fire()
                return real[kind](*args, **kwargs)

            return call

        def rename(*args, **kwargs):
            if self._point == "rename":
                self._fire()
            return real["rename"](*args, **kwargs)

        def cleanup(kind):
            def call(*args, **kwargs):
                if self.armed and self._cleanup and self._cleanup[0] == kind:
                    raise self._cleanup[1]()
                return real[kind](*args, **kwargs)

            return call

        def close(fd):
            mine = fd in (self.mine.get(name) for name in self._close)
            if fd in self.mine.values():
                self.closed.append(fd)
            real["close"](fd)
            if self.zero is None and fd in self.mine.values():
                # an unrelated descriptor now owns the number just freed: a second close of it
                # would break this one
                self.zero = os.open("/dev/zero", os.O_RDONLY)
            if mine and self.closed.count(fd) == 1:
                raise OSError(errno.EIO, "injected")

        monkeypatch.setattr(redeye_output, "_open_out_dir", open_out)
        monkeypatch.setattr(redeye_output, "_new_run_dir", new_run)
        monkeypatch.setattr(redeye_output, "_refuse_if_contained", contained)
        monkeypatch.setattr(os, "write", counted("write"))
        monkeypatch.setattr(os, "fsync", counted("fsync"))
        monkeypatch.setattr(os, "rename", rename)
        monkeypatch.setattr(os, "unlink", cleanup("unlink"))
        monkeypatch.setattr(os, "rmdir", cleanup("rmdir"))
        monkeypatch.setattr(os, "close", close)


def _check_kept(out, outcome, name, close) -> None:
    """A close error comes after the complete bundle was kept."""
    (run,) = list(out.iterdir())
    for file, text in BUNDLE.items():
        assert (run / file).read_bytes() == text.encode()
    if close:
        assert isinstance(outcome, ManifestError)
    else:
        assert outcome is None and name == run.name


def _check_failed(out, outcome, expected, cleanup) -> None:
    if isinstance(expected, OSError):
        assert isinstance(outcome, ManifestError)
        assert outcome.__cause__ is expected
    else:
        assert outcome is expected  # the original, never a cleanup or close error
    leftovers = list(out.iterdir())
    if cleanup == "none":
        assert leftovers == []  # everything this call created is gone
        return
    # Cleanup itself was interrupted or refused: whatever it did not get to stays, but only the
    # one run directory this call made (with the files created so far), nothing else.
    assert len(leftovers) <= 1
    if cleanup.startswith("rmdir"):
        assert not list(leftovers[0].iterdir())  # the files went; only the directory is left


@pytest.mark.parametrize("cell", list(_cells()))
def test_every_descriptor_is_closed_once_and_the_original_failure_wins(
    tmp_path, monkeypatch, cell
) -> None:
    point, original, cleanup, close = cell
    out = tmp_path / "out"
    before = _open_fds()
    harness = _Harness(monkeypatch, point, original, cleanup, close)
    outcome: BaseException | None = None
    name = ""
    try:
        name = write_outputs(out, BUNDLE)
    except BaseException as error:  # KeyboardInterrupt and SystemExit are under test
        outcome = error
    monkeypatch.undo()
    try:
        assert harness.zero is not None
        assert os.read(harness.zero, 1) == b"\0"  # still usable: nobody closed it
    finally:
        if harness.zero is not None:
            os.close(harness.zero)
    assert _open_fds() == before  # no descriptor leaked, none closed twice
    assert set(harness.mine) == {"out", "run"}
    for fd in harness.mine.values():
        assert harness.closed.count(fd) == 1  # each of our two directories closed exactly once
    if point is None:
        _check_kept(out, outcome, name, close)
    else:
        _check_failed(out, outcome, harness.original, cleanup)
