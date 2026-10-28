"""Fifth review pass: every run writes a new directory; containment is by identity and is
checked again after the last file; nothing a failed run created stays behind."""

import errno
import os
import threading
from datetime import UTC, datetime

import pytest

from fastfoto_linux.evaluation import redeye_output
from fastfoto_linux.evaluation.redeye_manifest import ManifestError
from fastfoto_linux.evaluation.redeye_output import write_outputs

pytestmark = pytest.mark.usefixtures("outside_checkout")
BUNDLE = {"report.json": "R", "summary.md": "S", "perf.json": "P"}


def _runs(out):
    return sorted(p for p in out.iterdir() if p.name.startswith("run-"))


def _identity(path):
    info = path.stat()
    return (info.st_dev, info.st_ino)


def _hook_open(monkeypatch, name, action):
    """Call ``action`` once, right after the file called ``name`` was opened by the writer."""
    real, done = os.open, []

    def hooked(path, *args, **kwargs):
        fd = real(path, *args, **kwargs)
        if str(path) == name and not done:
            done.append(1)
            action()
        return fd

    monkeypatch.setattr(redeye_output.os, "open", hooked)


# --- write-once run directories -------------------------------------------------------------


def test_each_call_writes_a_new_private_run_directory_and_keeps_the_old_ones(tmp_path) -> None:
    out = tmp_path / "out"
    first = write_outputs(out, BUNDLE)
    second = write_outputs(out, {name: text.lower() for name, text in BUNDLE.items()})
    assert first != second
    assert (out / first / "report.json").read_text() == "R"
    assert (out / second / "report.json").read_text() == "r"
    assert sorted(p.name for p in out.iterdir()) == sorted([first, second])  # no lock, no temp
    assert ((out / first).stat().st_mode & 0o777) == 0o700
    assert ((out / first / "report.json").stat().st_mode & 0o777) == 0o600


def test_the_name_returned_is_the_run_directory(tmp_path) -> None:
    out = tmp_path / "out"
    name = write_outputs(out, BUNDLE)
    assert [p.name for p in _runs(out)] == [name]


def test_report_json_is_published_last_from_a_synced_temp_file(tmp_path, monkeypatch) -> None:
    events, real_open, real_rename = [], os.open, os.rename

    def recording_open(path, *args, **kwargs):
        events.append(("open", str(path)))
        return real_open(path, *args, **kwargs)

    def recording_rename(src, dst, **kwargs):
        events.append(("rename", f"{src}>{dst}"))
        return real_rename(src, dst, **kwargs)

    monkeypatch.setattr(redeye_output.os, "open", recording_open)
    monkeypatch.setattr(redeye_output.os, "rename", recording_rename)
    write_outputs(tmp_path / "out", BUNDLE)
    ours = [e for e in events if e[1] in (*BUNDLE, ".report.tmp", ".report.tmp>report.json")]
    assert ("open", "report.json") not in ours  # never opened for writing in place
    assert ours[-1] == ("rename", ".report.tmp>report.json")
    assert sorted(n for k, n in ours if k == "open") == sorted(
        [".report.tmp", "summary.md", "perf.json"]
    )
    assert ours.index(("open", ".report.tmp")) > ours.index(("open", "perf.json"))


def test_two_writers_never_share_a_directory_even_if_one_pauses(tmp_path, monkeypatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    release, paused = threading.Event(), threading.Event()
    real = os.open

    def pausing(path, *args, **kwargs):
        fd = real(path, *args, **kwargs)
        if str(path) == "summary.md" and threading.current_thread().name == "A":
            paused.set()
            assert release.wait(10)
        return fd

    monkeypatch.setattr(redeye_output.os, "open", pausing)
    first = threading.Thread(
        target=write_outputs, args=(out, {n: "A" for n in BUNDLE}), name="A", daemon=True
    )
    first.start()
    assert paused.wait(10)
    write_outputs(out, {n: "B" for n in BUNDLE})
    release.set()
    first.join(10)
    runs = _runs(out)
    assert len(runs) == 2
    for run in runs:
        assert len({(run / n).read_text() for n in BUNDLE}) == 1, run


@pytest.mark.parametrize("failing", ["summary.md", "perf.json", ".report.tmp"])
def test_a_failed_write_removes_what_this_call_created_and_touches_nothing_else(
    tmp_path, monkeypatch, failing
) -> None:
    out = tmp_path / "out"
    write_outputs(out, BUNDLE)
    before = {p: p.read_text() for p in out.rglob("*") if p.is_file()}
    real = os.open

    def failing_open(path, *args, **kwargs):
        if str(path) == failing:
            raise OSError(errno.EIO, "injected")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(redeye_output.os, "open", failing_open)
    with pytest.raises(ManifestError):
        write_outputs(out, {n: "NEW" for n in BUNDLE})
    assert {p: p.read_text() for p in out.rglob("*") if p.is_file()} == before
    assert len(_runs(out)) == 1


def test_a_directory_named_like_an_output_file_does_not_matter(tmp_path) -> None:
    out = tmp_path / "out"
    (out / "perf.json").mkdir(parents=True)
    name = write_outputs(out, BUNDLE)
    assert (out / name / "report.json").read_text() == "R"
    assert (out / "perf.json").is_dir()


# --- containment by identity, before and after ----------------------------------------------


def test_an_out_dir_renamed_into_the_corpus_after_the_last_write_leaves_nothing(
    tmp_path, monkeypatch
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    _hook_open(monkeypatch, ".report.tmp", lambda: out.rename(corpus / "moved"))
    with pytest.raises(ManifestError):
        write_outputs(out, BUNDLE, forbidden=[_identity(corpus)])
    assert [p for p in corpus.rglob("*") if p.is_file()] == []
    assert list((corpus / "moved").iterdir()) == []


def test_an_out_dir_moved_beneath_the_renamed_corpus_is_still_refused(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    identity = _identity(corpus)  # taken while the corpus still had its name
    corpus.rename(tmp_path / "renamed-corpus")
    out.rename(tmp_path / "renamed-corpus" / "results")
    with pytest.raises(ManifestError):
        write_outputs(tmp_path / "renamed-corpus" / "results", BUNDLE, forbidden=[identity])
    assert [p for p in (tmp_path / "renamed-corpus").rglob("*") if p.is_file()] == []


def test_a_directory_removed_before_the_run_is_refused(tmp_path, monkeypatch) -> None:
    out = tmp_path / "out"
    real = redeye_output._open_out_dir

    def removing(*args, **kwargs):
        fd = real(*args, **kwargs)
        out.rmdir()
        return fd

    monkeypatch.setattr(redeye_output, "_open_out_dir", removing)
    with pytest.raises(ManifestError):
        write_outputs(out, BUNDLE)


def test_a_run_directory_name_that_exists_is_never_reused(tmp_path, monkeypatch) -> None:
    out = tmp_path / "out"
    monkeypatch.setattr(redeye_output.secrets, "token_hex", lambda _: "deadbeef")

    class _Clock:
        @staticmethod
        def now(_tz):
            return datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    monkeypatch.setattr(redeye_output, "datetime", _Clock)
    first = write_outputs(out, BUNDLE)
    assert first == "run-20260102T030405Z-deadbeef"
    assert (out / first / "summary.md").read_text() == "S"
    with pytest.raises(ManifestError):
        write_outputs(out, {n: "NEW" for n in BUNDLE})
    assert (out / first / "report.json").read_text() == "R"


@pytest.mark.parametrize("kind", ["symlink", "file"])
def test_a_file_planted_in_the_run_directory_is_not_written_through(
    tmp_path, monkeypatch, kind
) -> None:
    out = tmp_path / "out"
    victim = tmp_path / "victim"
    victim.write_text("KEEP")
    real = redeye_output._new_run_dir

    def planting(out_fd):
        name, run_fd = real(out_fd)
        if kind == "symlink":
            os.symlink(victim, "summary.md", dir_fd=run_fd)
        else:
            os.close(os.open("summary.md", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=run_fd))
        return name, run_fd

    monkeypatch.setattr(redeye_output, "_new_run_dir", planting)
    with pytest.raises(ManifestError):
        write_outputs(out, BUNDLE)
    assert victim.read_text() == "KEEP"
    (run,) = _runs(out)  # not ours to remove: only what this call created is
    planted = run / "summary.md"
    assert [p.name for p in run.iterdir()] == ["summary.md"]
    assert planted.is_symlink() == (kind == "symlink")
    if kind == "file":
        assert planted.read_bytes() == b""  # still the empty file that was planted


def test_an_out_dir_already_inside_a_forbidden_tree_gets_no_file_at_all(
    tmp_path, monkeypatch
) -> None:
    corpus = tmp_path / "corpus"
    (corpus / "results").mkdir(parents=True)
    names, real = [], os.open

    def recording(path, *args, **kwargs):
        names.append(str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(redeye_output.os, "open", recording)
    with pytest.raises(ManifestError):
        write_outputs(corpus / "results", BUNDLE, forbidden=[_identity(corpus)])
    assert not [n for n in names if n in BUNDLE]  # refused before the run directory was made
    assert list((corpus / "results").iterdir()) == []
