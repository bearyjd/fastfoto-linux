"""Ninth review pass: a close that fails is translated like the read it follows, and reading a
file costs about one copy of it in memory."""

import errno
import io
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.evaluation import redeye_output
from fastfoto_linux.evaluation.redeye_images import BudgetExceeded, ImageError, read_contained
from fastfoto_linux.evaluation.redeye_manifest import ManifestError, load_manifest
from fastfoto_linux.evaluation.redeye_output import write_outputs
from tests.redeye_eval.synth import positive, write_corpus

BUNDLE = {"report.json": "R" * 50, "summary.md": "S" * 50, "perf.json": "P" * 50}
MIB = 1024 * 1024
_RUN_FILE = r"/run-[^/]+/[^/]+$"  # a file in the run directory, not the directory


@pytest.fixture(autouse=True)
def _outside(outside_checkout):
    return None


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


def _fail_close_of(monkeypatch, marker: str) -> list[int]:
    """Close descriptors whose path matches the regex ``marker`` for real, then raise EIO; the
    list holds every descriptor so closed (a second entry for one number is a double close)."""
    real, closed = os.close, []

    def close(fd):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            target = ""
        real(fd)
        if re.search(marker, target):
            closed.append(fd)
            raise OSError(errno.EIO, "injected")

    monkeypatch.setattr(os, "close", close)
    return closed


def _raise_from_read(monkeypatch, error: BaseException, marker: str) -> None:
    real = os.read

    def read(fd, count):
        if re.search(marker, os.readlink(f"/proc/self/fd/{fd}")):
            raise error
        return real(fd, count)

    monkeypatch.setattr(os, "read", read)


def test_a_close_that_fails_after_a_good_read_is_unreadable(tmp_path, monkeypatch) -> None:
    (tmp_path / "f").write_bytes(b"x" * 10)
    before = _open_fds()
    closed = _fail_close_of(monkeypatch, r"/f$")
    with pytest.raises(ImageError) as caught:
        read_contained(tmp_path, "f")
    monkeypatch.undo()
    assert caught.value.code == "unreadable"
    assert len(closed) == 1  # closed once, never twice
    assert _open_fds() == before


def test_a_close_that_fails_after_a_failed_read_keeps_the_read_failure(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "f").write_bytes(b"x" * 10)

    def charge(size):
        raise BudgetExceeded

    before = _open_fds()
    closed = _fail_close_of(monkeypatch, r"/f$")
    with pytest.raises(BudgetExceeded):
        read_contained(tmp_path, "f", charge)
    monkeypatch.undo()
    assert len(closed) == 1
    assert _open_fds() == before


def test_a_close_that_fails_after_an_interrupt_keeps_the_interrupt(tmp_path, monkeypatch) -> None:
    (tmp_path / "f").write_bytes(b"x" * 10)
    before = _open_fds()
    closed = _fail_close_of(monkeypatch, r"/f$")
    _raise_from_read(monkeypatch, KeyboardInterrupt(), r"/f$")
    with pytest.raises(KeyboardInterrupt):
        read_contained(tmp_path, "f")
    monkeypatch.undo()
    assert len(closed) == 1
    assert _open_fds() == before


def test_a_manifest_whose_close_fails_is_a_manifest_error(tmp_path, monkeypatch) -> None:
    path = write_corpus(tmp_path / "corpus", [positive("a")])  # valid: only the close can fail
    before = _open_fds()
    closed = _fail_close_of(monkeypatch, re.escape(path.name) + "$")
    with pytest.raises(ManifestError):
        load_manifest(path)
    monkeypatch.undo()
    assert len(closed) == 1
    assert _open_fds() == before


def test_a_manifest_close_failure_after_an_interrupt_keeps_the_interrupt(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{}")
    before = _open_fds()
    closed = _fail_close_of(monkeypatch, r"manifest\.json$")
    _raise_from_read(monkeypatch, KeyboardInterrupt(), r"manifest\.json$")
    with pytest.raises(KeyboardInterrupt):
        load_manifest(path)
    monkeypatch.undo()
    assert len(closed) == 1
    assert _open_fds() == before


def test_a_checkout_check_whose_close_fails_is_a_manifest_error(tmp_path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        before = _open_fds()
        closed = _fail_close_of(monkeypatch, r"pyproject\.toml$")
        with pytest.raises(ManifestError):
            redeye_output._fd_is_checkout(fd)
        monkeypatch.undo()
        assert len(closed) == 1
        assert _open_fds() == before
    finally:
        os.close(fd)


def test_a_checkout_check_close_failure_after_an_interrupt_keeps_the_interrupt(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        before = _open_fds()
        closed = _fail_close_of(monkeypatch, r"pyproject\.toml$")
        _raise_from_read(monkeypatch, KeyboardInterrupt(), r"pyproject\.toml$")
        with pytest.raises(KeyboardInterrupt):
            redeye_output._fd_is_checkout(fd)
        monkeypatch.undo()
        assert len(closed) == 1
        assert _open_fds() == before
    finally:
        os.close(fd)


def test_an_output_file_whose_close_fails_is_a_manifest_error_after_cleanup(
    tmp_path, monkeypatch
) -> None:
    out = tmp_path / "out"
    before = _open_fds()
    closed = _fail_close_of(monkeypatch, _RUN_FILE)
    with pytest.raises(ManifestError):
        write_outputs(out, BUNDLE)
    monkeypatch.undo()
    assert len(closed) == 1  # the first file failed, nothing went on to a second
    assert list(out.iterdir()) == []
    assert _open_fds() == before


def test_an_output_close_failure_after_an_interrupt_keeps_the_interrupt(
    tmp_path, monkeypatch
) -> None:
    real = os.write

    def interrupt(fd, data):
        if re.search(_RUN_FILE, os.readlink(f"/proc/self/fd/{fd}")):
            raise KeyboardInterrupt
        return real(fd, data)

    out = tmp_path / "out"
    before = _open_fds()
    closed = _fail_close_of(monkeypatch, _RUN_FILE)
    monkeypatch.setattr(os, "write", interrupt)
    with pytest.raises(KeyboardInterrupt):
        write_outputs(out, BUNDLE)
    monkeypatch.undo()
    assert len(closed) == 1
    assert _open_fds() == before


_READ_SCRIPT = textwrap.dedent(
    """
    import resource, sys
    from pathlib import Path
    from fastfoto_linux.evaluation.redeye_images import read_contained

    def vm_bytes():
        for line in open("/proc/self/status"):
            if line.startswith("VmSize:"):
                return int(line.split()[1]) * 1024

    allowed = vm_bytes() + 48 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (allowed, allowed))
    path = Path(sys.argv[1])
    data = read_contained(path.parent, path.name)
    print(len(data))
    """
)


def test_reading_a_32_mib_file_costs_about_one_copy(tmp_path) -> None:
    png = io.BytesIO()
    Image.new("RGB", (1, 1), (200, 30, 30)).save(png, "PNG")
    path = tmp_path / "padded.png"
    with path.open("wb") as file:
        file.write(png.getvalue())
        file.truncate(32 * MIB)  # a hole: fast and sparse
    try:
        result = subprocess.run(
            [sys.executable, "-c", _READ_SCRIPT, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[2] / "src")},
        )
    finally:
        path.unlink()
    assert result.returncode == 0, result.stderr[-400:]
    assert result.stdout.strip() == str(32 * MIB)
