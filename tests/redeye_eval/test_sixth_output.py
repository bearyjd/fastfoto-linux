"""Sixth review pass, results directory: a present report.json is complete, every failure is a
ManifestError, no descriptor leaks, and run names retry on a collision."""

import errno
import itertools
import os
from datetime import UTC, datetime

import pytest

from fastfoto_linux.evaluation import redeye_output
from fastfoto_linux.evaluation.redeye_manifest import ManifestError
from fastfoto_linux.evaluation.redeye_output import write_outputs

BUNDLE = {"report.json": "R", "summary.md": "S", "perf.json": "P"}


def _runs(out):
    return sorted(p for p in out.iterdir() if p.name.startswith("run-"))


def _identity(path):
    info = path.stat()
    return (info.st_dev, info.st_ino)


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


# --- report.json is the completion marker ---------------------------------------------------


@pytest.mark.usefixtures("outside_checkout")
def test_a_writer_killed_while_filling_the_report_leaves_no_report_json(tmp_path) -> None:
    out = tmp_path / "out"
    pid = os.fork()
    if pid == 0:  # the child dies (as if SIGKILLed) right after the report file exists
        code = 3
        try:
            real = os.open

            def killing(path, *args, **kwargs):
                fd = real(path, *args, **kwargs)
                if str(path) in ("report.json", ".report.tmp"):
                    os.write(fd, b"{")
                    os._exit(0)
                return fd

            redeye_output.os.open = killing
            write_outputs(out, BUNDLE)
        finally:
            os._exit(code)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    (run,) = _runs(out)
    assert not (run / "report.json").exists()


@pytest.mark.usefixtures("outside_checkout")
def test_a_finished_run_directory_holds_exactly_the_bundle(tmp_path) -> None:
    out = tmp_path / "out"
    name = write_outputs(out, BUNDLE)
    assert sorted(p.name for p in (out / name).iterdir()) == sorted(BUNDLE)
    assert ((out / name / "report.json").stat().st_mode & 0o777) == 0o600


@pytest.mark.usefixtures("outside_checkout")
def test_a_failed_publish_removes_the_temp_file_and_the_run_directory(
    tmp_path, monkeypatch
) -> None:
    out = tmp_path / "out"

    def failing_link(*args, **kwargs):
        raise OSError(errno.EIO, "injected")

    monkeypatch.setattr(redeye_output.os, "link", failing_link)
    with pytest.raises(ManifestError):
        write_outputs(out, BUNDLE)
    assert list(out.iterdir()) == []


# --- every failure is a ManifestError -------------------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
@pytest.mark.usefixtures("outside_checkout")
def test_an_unreadable_ancestor_is_a_manifest_error(tmp_path) -> None:
    locked = tmp_path / "locked"
    (locked / "inner").mkdir(parents=True)
    locked.chmod(0)
    try:
        with pytest.raises(ManifestError):
            write_outputs(locked / "inner" / "out", BUNDLE)
    finally:
        locked.chmod(0o700)


@pytest.mark.usefixtures("outside_checkout")
def test_text_that_cannot_be_encoded_is_a_manifest_error_and_leaves_nothing(tmp_path) -> None:
    out = tmp_path / "out"
    with pytest.raises(ManifestError):
        write_outputs(out, {**BUNDLE, "summary.md": "lone surrogate \ud800"})
    assert _runs(out) == []


# --- containment: the corpus appears between two files --------------------------------------


@pytest.mark.usefixtures("outside_checkout")
def test_an_out_dir_renamed_into_the_corpus_between_two_files_leaves_nothing(
    tmp_path, monkeypatch
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    real, done = os.open, []

    def renaming(path, *args, **kwargs):
        fd = real(path, *args, **kwargs)
        if str(path) == "perf.json" and not done:  # the second file of the loop
            done.append(1)
            out.rename(corpus / "moved")
        return fd

    monkeypatch.setattr(redeye_output.os, "open", renaming)
    with pytest.raises(ManifestError):
        write_outputs(out, BUNDLE, forbidden=[_identity(corpus)])
    assert done
    assert [p for p in corpus.rglob("*") if p.is_file()] == []
    assert list((corpus / "moved").iterdir()) == []


# --- descriptors ----------------------------------------------------------------------------


def test_a_failing_fstat_during_the_ascent_closes_every_descriptor(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "a" / "b"
    directory.mkdir(parents=True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        before = _open_fds()
        real, calls = os.fstat, []

        def failing(target, *args, **kwargs):
            calls.append(1)
            if len(calls) == 2:  # the one on the first parent
                raise OSError(errno.EIO, "injected")
            return real(target, *args, **kwargs)

        monkeypatch.setattr(redeye_output.os, "fstat", failing)
        with pytest.raises(ManifestError):
            redeye_output._refuse_if_contained(fd, frozenset())
        monkeypatch.undo()
        assert len(calls) == 2
        assert _open_fds() == before
    finally:
        os.close(fd)


@pytest.mark.usefixtures("outside_checkout")
def test_a_failing_fdopen_leaks_no_descriptor(tmp_path, monkeypatch) -> None:
    out = tmp_path / "out"
    write_outputs(out, BUNDLE)  # the output directories exist already
    before = _open_fds()

    def failing(*args, **kwargs):
        raise OSError(errno.EMFILE, "injected")

    monkeypatch.setattr(redeye_output.os, "fdopen", failing)
    with pytest.raises(ManifestError):
        write_outputs(out, BUNDLE)
    monkeypatch.undo()
    assert _open_fds() == before
    assert len(_runs(out)) == 1


# --- run names ------------------------------------------------------------------------------


class _Clock:
    @staticmethod
    def now(_tz):
        return datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.mark.usefixtures("outside_checkout")
def test_a_name_collision_retries_with_a_new_token(tmp_path, monkeypatch) -> None:
    out = tmp_path / "out"
    monkeypatch.setattr(redeye_output, "datetime", _Clock)
    tokens = itertools.chain(["deadbeef", "deadbeef", "cafebabe"], itertools.repeat("cafebabe"))
    monkeypatch.setattr(redeye_output.secrets, "token_hex", lambda _: next(tokens))
    first = write_outputs(out, BUNDLE)
    second = write_outputs(out, BUNDLE)  # deadbeef is taken: the next token is used
    assert (first, second) == ("run-20260102T030405Z-deadbeef", "run-20260102T030405Z-cafebabe")
    monkeypatch.setattr(redeye_output.secrets, "token_hex", lambda _: "cafebabe")
    with pytest.raises(ManifestError):  # three tries, all taken: a clean error
        write_outputs(out, BUNDLE)
    assert len(_runs(out)) == 2
