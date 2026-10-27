"""Fifth review pass: the corpus root is pinned from the manifest's own directory, and a read
that fails at the device level is an unreadable image, not a crash."""

import errno
import os
from pathlib import Path

import pytest

from fastfoto_linux.evaluation import redeye_images
from fastfoto_linux.evaluation.redeye_images import ImageError, read_contained
from fastfoto_linux.evaluation.redeye_manifest import ManifestError, load_manifest
from fastfoto_linux.evaluation.redeye_run import run_eval
from tests.redeye_eval.synth import KeyedDetector, clean_heldout_set, write_corpus


def _two_corpora(tmp_path):
    """parent/corpus holds the real set; outside/corpus has the same names, other bytes."""
    items = clean_heldout_set()
    inside = write_corpus(tmp_path / "parent" / "corpus", items)
    outside = tmp_path / "outside" / "corpus"
    outside.mkdir(parents=True)
    for item in items:
        (outside / f"{item.id}.png").write_bytes(b"EXTERNAL")
    (outside / "manifest.json").write_bytes(inside.read_bytes())
    return items, inside


def _swap_parent(tmp_path) -> None:
    (tmp_path / "parent").rename(tmp_path / "parent.aside")
    (tmp_path / "parent").symlink_to(tmp_path / "outside")


def test_an_ancestor_swapped_for_a_symlink_between_resolve_and_walk_is_refused(
    tmp_path, monkeypatch
) -> None:
    _, manifest_path = _two_corpora(tmp_path)
    real = Path.resolve

    def swapping(self, *args, **kwargs):
        resolved = real(self, *args, **kwargs)
        if self.name == "manifest.json" and not (tmp_path / "parent.aside").exists():
            _swap_parent(tmp_path)
        return resolved

    monkeypatch.setattr(Path, "resolve", swapping)
    with pytest.raises(ManifestError):
        load_manifest(manifest_path)


def test_a_run_reads_the_directory_the_manifest_came_from_after_an_ancestor_swap(
    tmp_path,
) -> None:
    items, manifest_path = _two_corpora(tmp_path)
    manifest = load_manifest(manifest_path)
    _swap_parent(tmp_path)
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    assert [r.id for r in run.results if r.error] == []


def test_a_loaded_manifest_knows_the_identity_of_its_directory(tmp_path) -> None:
    _, manifest_path = _two_corpora(tmp_path)
    manifest = load_manifest(manifest_path)
    info = manifest_path.parent.stat()
    assert manifest.identity == (info.st_dev, info.st_ino)


# --- a failing read is an unreadable image -----------------------------------------------


@pytest.mark.skipif(not Path("/proc/self/mem").exists(), reason="needs /proc")
def test_a_regular_file_whose_read_fails_with_eio_is_unreadable() -> None:
    with pytest.raises(ImageError) as info:
        read_contained(Path("/proc") / str(os.getpid()), "mem")
    assert info.value.code == "unreadable"


class _Failing:
    """A file object whose reads fail the way a dying disk's do."""

    def __init__(self, handle) -> None:
        self._handle = handle

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self._handle.close()

    def fileno(self) -> int:
        return self._handle.fileno()

    def read(self, *args):
        raise OSError(errno.EIO, "injected")


def _failing_reads(monkeypatch) -> None:
    real = os.fdopen
    monkeypatch.setattr(
        redeye_images.os, "fdopen", lambda fd, *a, **k: _Failing(real(fd, *a, **k))
    )


def test_a_heldout_item_that_cannot_be_read_is_a_counted_error(tmp_path, monkeypatch) -> None:
    items = clean_heldout_set()
    manifest = load_manifest(write_corpus(tmp_path / "c", items))
    _failing_reads(monkeypatch)
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    assert {r.error for r in run.results} == {"unreadable"}


def test_a_tuning_item_that_cannot_be_read_refuses_the_run(tmp_path, monkeypatch) -> None:
    items = clean_heldout_set()
    path = write_corpus(tmp_path / "c", items, splits={i.id: "tuning" for i in items[:1]})
    manifest = load_manifest(path)
    _failing_reads(monkeypatch)
    with pytest.raises(ManifestError, match="cannot be read"):
        run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
