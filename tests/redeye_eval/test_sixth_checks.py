"""Sixth review pass: checkout detection fails closed, Manifest.close is idempotent, the reader
closes its descriptor, and a run has a byte budget."""

import contextlib
import errno
import os
import stat

import pytest

from fastfoto_linux.evaluation import redeye_images, redeye_manifest, redeye_run
from fastfoto_linux.evaluation.redeye_images import BudgetExceeded, ImageError, read_regular_fd
from fastfoto_linux.evaluation.redeye_manifest import ManifestError, load_manifest
from fastfoto_linux.evaluation.redeye_output import _refuse_if_contained
from fastfoto_linux.evaluation.redeye_run import run_eval
from tests.redeye_eval.synth import KeyedDetector, positive, with_split, write_corpus

OURS = b'[project]\nname = "fastfoto-linux"\n'
_DIR = os.O_RDONLY | os.O_DIRECTORY


def _ascend(directory) -> None:
    fd = os.open(directory, _DIR)
    try:
        _refuse_if_contained(fd, frozenset())
    finally:
        os.close(fd)


def _repo(tmp_path, pyproject: bytes | None):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    if pyproject is not None:
        (repo / "pyproject.toml").write_bytes(pyproject)
    return repo


def _failing_pyproject(monkeypatch, code: int) -> None:
    real = os.open

    def failing(path, *args, **kwargs):
        if str(path) == "pyproject.toml":
            raise OSError(code, "injected")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(redeye_images.os, "open", failing)


# --- checkout detection ---------------------------------------------------------------------


def test_our_checkout_is_refused(tmp_path) -> None:
    with pytest.raises(ManifestError, match="checkout"):
        _ascend(_repo(tmp_path, OURS))


@pytest.mark.parametrize("code", [errno.EIO, errno.EACCES])
def test_a_pyproject_that_cannot_be_opened_refuses_the_location(
    tmp_path, monkeypatch, code
) -> None:
    repo = _repo(tmp_path, OURS)
    _failing_pyproject(monkeypatch, code)
    with pytest.raises(ManifestError, match="cannot verify the output location"):
        _ascend(repo)


@pytest.mark.parametrize("code", [errno.ENOENT, errno.ENOTDIR, errno.ELOOP])
def test_a_missing_or_symlinked_pyproject_is_not_a_checkout(tmp_path, monkeypatch, code) -> None:
    repo = _repo(tmp_path, OURS)
    _failing_pyproject(monkeypatch, code)
    _ascend(repo)


def test_a_pyproject_symlink_is_not_a_checkout(tmp_path) -> None:
    repo = _repo(tmp_path, None)
    (tmp_path / "real.toml").write_bytes(OURS)
    (repo / "pyproject.toml").symlink_to(tmp_path / "real.toml")
    _ascend(repo)


@pytest.mark.parametrize(
    "content",
    [
        b"[[[[",
        b"\xff\xfe\x00",
        b"a = " + b"[" * 100_000,  # RecursionError in the parser
        b"project = 1",
        b'[project]\nname = "other"\n',
    ],
    ids=["syntax", "not-utf8", "deeply-nested", "project-not-a-table", "foreign-name"],
)
def test_a_foreign_or_malformed_pyproject_does_not_block_output(tmp_path, content) -> None:
    _ascend(_repo(tmp_path, content))


def test_a_pyproject_that_fails_to_read_refuses_the_location(tmp_path, monkeypatch) -> None:
    repo = _repo(tmp_path, OURS)
    real = os.fstat

    def failing(fd, *args, **kwargs):
        info = real(fd, *args, **kwargs)
        if stat.S_ISREG(info.st_mode):  # only the pyproject, not the directories
            raise OSError(errno.EIO, "injected")
        return info

    monkeypatch.setattr(redeye_images.os, "fstat", failing)
    with pytest.raises(ManifestError, match="cannot verify the output location"):
        _ascend(repo)


# --- Manifest.close -------------------------------------------------------------------------


def test_closing_a_manifest_twice_closes_its_descriptor_once(tmp_path, monkeypatch) -> None:
    manifest = load_manifest(write_corpus(tmp_path / "c", [positive("a")]))
    fd, closed, real = manifest.root_fd, [], os.close

    def recording(target):
        closed.append(target)
        real(target)

    monkeypatch.setattr(redeye_manifest.os, "close", recording)
    manifest.close()
    manifest.close()
    assert closed == [fd]


def test_a_manifest_is_a_context_manager(tmp_path) -> None:
    with load_manifest(write_corpus(tmp_path / "c", [positive("a")])) as manifest:
        fd = manifest.root_fd
        os.fstat(fd)
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(fd)


# --- the reader's descriptor ----------------------------------------------------------------


def test_read_regular_fd_closes_the_descriptor_when_fdopen_fails(tmp_path, monkeypatch) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"x")
    fd = os.open(path, os.O_RDONLY)

    def failing(*args, **kwargs):
        raise OSError(errno.EMFILE, "injected")

    try:
        monkeypatch.setattr(redeye_images.os, "fdopen", failing)
        with pytest.raises(ImageError):
            read_regular_fd(fd, 10)
        monkeypatch.undo()
        with pytest.raises(OSError, match="Bad file descriptor"):
            os.fstat(fd)
    finally:
        monkeypatch.undo()
        with contextlib.suppress(OSError):
            os.close(fd)


# --- the byte budget ------------------------------------------------------------------------


def test_the_size_is_charged_before_a_byte_is_read(tmp_path) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"x" * 7)
    seen: list[int] = []
    read_regular_fd(os.open(path, os.O_RDONLY), 100, charge=seen.append)
    assert seen == [7]

    def refusing(size: int) -> None:
        raise BudgetExceeded

    with pytest.raises(BudgetExceeded):
        read_regular_fd(os.open(path, os.O_RDONLY), 100, charge=refusing)


def test_a_run_over_its_byte_budget_counts_tuning_images_too(tmp_path, monkeypatch) -> None:
    held = with_split(positive("held"), "heldout")
    tune = with_split(positive("tune", centre=(150, 100)), "tuning")
    manifest = load_manifest(write_corpus(tmp_path / "c", [held, tune]))
    total = len(held.png()) + len(tune.png())
    monkeypatch.setattr(redeye_run, "MAX_RUN_BYTES", total - 1, raising=False)
    with pytest.raises(ManifestError, match="budget"):
        run_eval(manifest, "heldout", detector=KeyedDetector([held]), perf=False)
    monkeypatch.setattr(redeye_run, "MAX_RUN_BYTES", total, raising=False)
    run_eval(manifest, "heldout", detector=KeyedDetector([held]), perf=False)
