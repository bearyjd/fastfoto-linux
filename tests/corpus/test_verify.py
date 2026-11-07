"""Verifying corpus files: hashes, symlinks, FIFOs, pinned root, descriptors."""

import os

import pytest

from fastfoto_linux.evaluation import corpus_manifest
from fastfoto_linux.evaluation.corpus_manifest import (
    CorpusError,
    load_corpus_manifest,
    verify_hashes,
)
from tests.corpus.helpers import document, encode, raw_item, sha, write_corpus


def _fds() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_matching_files_verify_including_nested_ones(tmp_path) -> None:
    manifest = write_corpus(tmp_path, {"a.bin": b"alpha", "sub/dir/b.bin": b"beta"})
    with load_corpus_manifest(manifest) as loaded:
        assert len(loaded.items) == 2


def test_verify_false_reads_no_file(tmp_path) -> None:
    (tmp_path / "MANIFEST.json").write_bytes(encode(document([raw_item()])))
    with load_corpus_manifest(tmp_path / "MANIFEST.json", verify=False) as loaded:
        assert loaded.items[0].id == "item-a"


def test_a_content_mismatch_names_the_id_only(tmp_path) -> None:
    manifest = write_corpus(tmp_path, {"SENTINELDIR/a.bin": b"alpha"})
    (tmp_path / "SENTINELDIR" / "a.bin").write_bytes(b"changed")
    with pytest.raises(CorpusError, match="does not match") as info:
        load_corpus_manifest(manifest)
    assert "item-f0" in str(info.value)
    assert "SENTINELDIR" not in str(info.value) and sha(b"alpha") not in str(info.value)


def test_a_missing_file_is_refused(tmp_path) -> None:
    manifest = write_corpus(tmp_path, {"a.bin": b"alpha"})
    (tmp_path / "a.bin").unlink()
    with pytest.raises(CorpusError, match="missing"):
        load_corpus_manifest(manifest)


def test_a_symlinked_file_is_refused(tmp_path) -> None:
    manifest = write_corpus(tmp_path, {"real.bin": b"alpha"})
    (tmp_path / "link.bin").symlink_to(tmp_path / "real.bin")
    doc = document([raw_item("l", b"alpha", path="link.bin")])
    manifest.write_bytes(encode(doc))
    with pytest.raises(CorpusError, match="unsafe"):
        load_corpus_manifest(manifest)


def test_a_symlinked_directory_is_refused(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "a.bin").write_bytes(b"alpha")
    (root / "dir").symlink_to(tmp_path / "other")
    (root / "MANIFEST.json").write_bytes(encode(document([raw_item(path="dir/a.bin")])))
    with pytest.raises(CorpusError, match="unsafe"):
        load_corpus_manifest(root / "MANIFEST.json")


def test_a_fifo_is_refused_without_blocking(tmp_path) -> None:
    os.mkfifo(tmp_path / "pipe.bin")
    # the empty hash would match if the FIFO were read as a file
    item = raw_item("p", b"", path="pipe.bin")
    (tmp_path / "MANIFEST.json").write_bytes(encode(document([item])))
    with pytest.raises(CorpusError, match="regular file"):
        load_corpus_manifest(tmp_path / "MANIFEST.json")


def test_a_fifo_manifest_is_refused(tmp_path) -> None:
    os.mkfifo(tmp_path / "MANIFEST.json")
    with pytest.raises(CorpusError, match="regular file"):
        load_corpus_manifest(tmp_path / "MANIFEST.json", verify=False)


def test_a_missing_manifest_is_a_corpus_error(tmp_path) -> None:
    with pytest.raises(CorpusError, match="cannot read"):
        load_corpus_manifest(tmp_path / "MANIFEST.json")


def test_a_file_over_the_size_cap_is_refused(tmp_path, monkeypatch) -> None:
    manifest = write_corpus(tmp_path, {"a.bin": b"alpha"})
    monkeypatch.setattr(corpus_manifest, "MAX_FILE_BYTES", 4)
    with pytest.raises(CorpusError, match="too large"):
        load_corpus_manifest(manifest)


def test_large_files_are_hashed_in_chunks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(corpus_manifest, "HASH_CHUNK", 3)
    manifest = write_corpus(tmp_path, {"a.bin": b"0123456789"})
    with load_corpus_manifest(manifest) as loaded:
        assert loaded.items[0].sha256 == sha(b"0123456789")


def test_files_are_read_through_the_pinned_directory_not_the_path(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    manifest = write_corpus(root, {"a.bin": b"alpha"})
    with load_corpus_manifest(manifest, verify=False) as loaded:
        root.rename(tmp_path / "moved")
        root.mkdir()
        (root / "a.bin").write_bytes(b"impostor")
        verify_hashes(loaded)  # the moved directory is what was pinned


def test_no_descriptor_leaks_on_success_or_failure(tmp_path) -> None:
    good = write_corpus(tmp_path / "good", {"a.bin": b"alpha", "b.bin": b"beta"})
    bad = write_corpus(tmp_path / "bad", {"a.bin": b"alpha"})
    (tmp_path / "bad" / "a.bin").write_bytes(b"changed")
    garbage = tmp_path / "garbage" / "MANIFEST.json"
    garbage.parent.mkdir()
    garbage.write_bytes(b"{")
    missing = write_corpus(tmp_path / "missing", {"a.bin": b"alpha"})
    (tmp_path / "missing" / "a.bin").unlink()
    before = _fds()
    with load_corpus_manifest(good):
        pass
    for path in (bad, garbage, missing):
        with pytest.raises(CorpusError):
            load_corpus_manifest(path)
    with pytest.raises(CorpusError):
        load_corpus_manifest(tmp_path / "absent" / "MANIFEST.json")
    assert _fds() == before
