"""Eighth review pass: the function that opens a descriptor closes it in its own ``finally``.

No helper takes over a descriptor, so nothing has to prove after the fact whether it is still
ours; these tests check the observable results (no leaked or foreign descriptor is touched).
"""

import contextlib
import errno
import json
import os

import pytest

from fastfoto_linux.evaluation import redeye_images, redeye_manifest, redeye_output
from fastfoto_linux.evaluation.redeye_images import ImageError, read_contained
from fastfoto_linux.evaluation.redeye_manifest import ManifestError, load_manifest
from fastfoto_linux.evaluation.redeye_output import write_outputs

BUNDLE = {"report.json": "R" * 50, "summary.md": "S" * 50, "perf.json": "P" * 50}


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


def _is_run_file(fd: int) -> bool:
    try:
        return "/run-" in os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return False


def _patch_write(monkeypatch, replacement):
    """Make ``os.write`` on a run-directory file call ``replacement(real_write, fd, data)``."""
    real = os.write

    def patched(fd, data):
        if _is_run_file(fd):
            return replacement(real, fd, data)
        return real(fd, data)

    monkeypatch.setattr(redeye_output.os, "write", patched)


def _no_space(real, fd, data):
    raise OSError(errno.ENOSPC, "injected")


@pytest.fixture(autouse=True)
def _outside(outside_checkout):
    return None


def test_a_read_that_fails_midway_is_unreadable_and_leaks_nothing(tmp_path, monkeypatch) -> None:
    (tmp_path / "f").write_bytes(b"x" * 10)
    target = (tmp_path / "f").stat().st_ino
    real = os.read

    def failing(fd, count):
        if os.fstat(fd).st_ino == target:
            raise OSError(errno.EIO, "injected")
        return real(fd, count)

    before = _open_fds()
    monkeypatch.setattr(redeye_images.os, "read", failing)
    with pytest.raises(ImageError) as caught:
        read_contained(tmp_path, "f")
    monkeypatch.undo()
    assert caught.value.code == "unreadable"
    assert _open_fds() == before


def test_a_failed_write_closes_its_descriptor_cleans_up_and_is_a_manifest_error(
    tmp_path, monkeypatch
) -> None:
    out = tmp_path / "out"
    before = _open_fds()
    _patch_write(monkeypatch, _no_space)
    with pytest.raises(ManifestError):
        write_outputs(out, BUNDLE)
    monkeypatch.undo()
    assert list(out.iterdir()) == []  # the run directory and its files are gone
    assert _open_fds() == before


def test_text_that_cannot_be_encoded_fails_before_any_file_is_created(
    tmp_path, monkeypatch
) -> None:
    out = tmp_path / "out"
    real, created = os.open, []

    def spying(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            created.append(path)
        return real(path, flags, *args, **kwargs)

    before = _open_fds()
    monkeypatch.setattr(redeye_output.os, "open", spying)
    with pytest.raises(ManifestError):
        write_outputs(out, {**BUNDLE, "summary.md": "lone \ud800 surrogate"})
    monkeypatch.undo()
    assert created == []
    assert not out.exists()  # refused before the output directory was even made
    assert _open_fds() == before


def test_short_writes_still_produce_identical_files(tmp_path, monkeypatch) -> None:
    calls: list[int] = []

    def one_byte(real, fd, data):
        calls.append(len(data))
        return real(fd, bytes(data[:1]))

    _patch_write(monkeypatch, one_byte)
    name = write_outputs(tmp_path / "out", BUNDLE)
    monkeypatch.undo()
    assert len(calls) > len(BUNDLE)
    for file, text in BUNDLE.items():
        assert (tmp_path / "out" / name / file).read_bytes() == text.encode()


def test_a_write_that_makes_no_progress_is_an_error_not_a_hang(tmp_path, monkeypatch) -> None:
    _patch_write(monkeypatch, lambda real, fd, data: 0)
    with pytest.raises(ManifestError):
        write_outputs(tmp_path / "out", BUNDLE)


def test_nobody_elses_descriptor_is_closed_by_a_failed_write(tmp_path, monkeypatch) -> None:
    replacement: list[int] = []

    def take_a_descriptor_then_fail(real, fd, data):
        replacement.append(os.open("/dev/zero", os.O_RDONLY))
        raise OSError(errno.ENOSPC, "injected")

    _patch_write(monkeypatch, take_a_descriptor_then_fail)
    try:
        with pytest.raises(ManifestError):
            write_outputs(tmp_path / "out", BUNDLE)
        monkeypatch.undo()
        assert os.read(replacement[0], 4) == b"\0\0\0\0"
    finally:
        for number in replacement:
            with contextlib.suppress(OSError):
                os.close(number)


def test_an_interrupt_from_a_write_propagates_unchanged_and_closes_the_descriptor(
    tmp_path, monkeypatch
) -> None:
    def interrupt(real, fd, data):
        raise KeyboardInterrupt

    before = _open_fds()
    _patch_write(monkeypatch, interrupt)
    with pytest.raises(KeyboardInterrupt):
        write_outputs(tmp_path / "out", BUNDLE)
    monkeypatch.undo()
    assert list((tmp_path / "out").iterdir()) == []
    assert _open_fds() == before


def test_a_manifest_that_fails_midway_is_a_manifest_error_and_leaks_nothing(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"format": "x"}))
    target = path.stat().st_ino
    real, failed = os.read, []

    def failing(fd, count):
        if os.fstat(fd).st_ino == target:
            failed.append(fd)
            raise OSError(errno.EIO, "injected")
        return real(fd, count)

    before = _open_fds()
    monkeypatch.setattr(redeye_manifest.os, "read", failing)
    with pytest.raises(ManifestError):
        load_manifest(path)
    monkeypatch.undo()
    assert failed  # the read went through os.read and failed there
    assert _open_fds() == before
