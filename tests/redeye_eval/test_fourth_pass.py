"""Fourth review pass: a pinned corpus root, per-write containment, a bounded multi-frame
check, a serialized output bundle and no directories left behind by a refused path."""

import io
import os
import struct
import threading
import time

import pytest
from PIL import Image, TiffImagePlugin

from fastfoto_linux.evaluation import redeye_images, redeye_output
from fastfoto_linux.evaluation.redeye_images import ImageError, decode_image, read_contained
from fastfoto_linux.evaluation.redeye_manifest import ManifestError, load_manifest
from fastfoto_linux.evaluation.redeye_output import write_outputs
from fastfoto_linux.evaluation.redeye_run import run_eval
from tests.redeye_eval.synth import KeyedDetector, clean_heldout_set, write_corpus

pytestmark = pytest.mark.usefixtures("outside_checkout")


def _files_in(root):
    return [p for p in root.rglob("*") if not p.is_dir()]


def _checkout(path):
    path.mkdir()
    (path / ".git").mkdir()
    (path / "pyproject.toml").write_text(f'[project]\nname = "{redeye_output.PROJECT_NAME}"\n')
    return path


# --- finding 2: the corpus root is pinned, never reopened by path -------------------------


def test_a_corpus_root_swapped_for_a_symlink_is_never_read_through(tmp_path) -> None:
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret").write_bytes(b"EXTERNAL")
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "secret").write_bytes(b"INTERNAL")
    root.rename(tmp_path / "aside")
    root.symlink_to(tmp_path / "outside")
    with pytest.raises(ImageError):
        read_contained(root, "secret")


def test_a_run_reads_every_image_from_the_original_root_after_a_swap(tmp_path, monkeypatch) -> None:
    items = clean_heldout_set()
    root = tmp_path / "corpus"
    manifest = load_manifest(write_corpus(root, items))
    decoys = tmp_path / "outside"
    decoys.mkdir()
    for item in items:
        (decoys / f"{item.id}.png").write_bytes(b"EXTERNAL")
    real, calls = redeye_images.load_image, []

    def swapping(*args, **kwargs):
        if not calls:  # after the first read
            root.rename(tmp_path / "aside")
            root.symlink_to(decoys)
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(redeye_images, "load_image", swapping)
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    assert len(calls) > 1
    assert [r.id for r in run.results if r.error] == []


# --- finding 3: the multi-frame check does not walk the IFD chain --------------------------


def _chained_tiff(count: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, "TIFF")
    data = bytearray(buffer.getvalue())
    bo = "<" if data[:2] == b"II" else ">"
    first = struct.unpack_from(bo + "I", data, 4)[0]
    entries = struct.unpack_from(bo + "H", data, first)[0]
    size = 2 + 12 * entries + 4
    base = len(data)
    ifd = bytes(data[first : first + size - 4])
    chain = bytearray()
    for k in range(count):
        following = base + (k + 1) * size if k + 1 < count else 0
        chain += ifd + struct.pack(bo + "I", following)
    struct.pack_into(bo + "I", data, first + size - 4, base)
    return bytes(data + chain)


def test_a_long_ifd_chain_is_multi_frame_without_walking_it(monkeypatch) -> None:
    data = _chained_tiff(20_000)
    real, loads = TiffImagePlugin.ImageFileDirectory_v2.load, []

    def counting(self, fp):
        loads.append(1)
        return real(self, fp)

    monkeypatch.setattr(TiffImagePlugin.ImageFileDirectory_v2, "load", counting)
    start = time.monotonic()
    with pytest.raises(ImageError) as info:
        decode_image(data)
    assert info.value.code == "multi_frame"
    assert time.monotonic() - start < 2.0
    assert len(loads) < 10  # the next IFD only, not the chain


# --- finding 1: containment is re-verified before every write and replace -----------------


@pytest.mark.parametrize("target", ["corpus", "checkout"])
def test_a_dir_renamed_into_a_forbidden_tree_before_the_first_write_is_refused(
    tmp_path, monkeypatch, target
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    inside = corpus if target == "corpus" else _checkout(tmp_path / "checkout")
    real = redeye_output._open_out_dir

    def racing(*args, **kwargs):
        fd = real(*args, **kwargs)
        out.rename(inside / "moved")
        return fd

    monkeypatch.setattr(redeye_output, "_open_out_dir", racing)
    with pytest.raises(ManifestError):
        write_outputs(out, {"report.json": "REPLACED"}, forbidden=[corpus])
    assert [p for p in _files_in(inside) if p.name != "pyproject.toml"] == []


def test_a_dir_renamed_into_the_corpus_between_two_files_gets_no_second_file(
    tmp_path, monkeypatch
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    real, calls = os.replace, []

    def racing(*args, **kwargs):
        real(*args, **kwargs)
        if not calls:
            calls.append(1)
            out.rename(corpus / "moved")

    monkeypatch.setattr(redeye_output.os, "replace", racing)
    files = {"report.json": "R", "summary.md": "S"}
    with pytest.raises(ManifestError):
        write_outputs(out, files, forbidden=[corpus])
    left = [p.name for p in _files_in(corpus) if p.name != ".write.lock"]
    assert len(left) <= 1, left  # only what was written before the move


# --- finding 4: concurrent bundles are never mixed ----------------------------------------


def test_two_concurrent_writers_never_leave_a_mixed_bundle(tmp_path, monkeypatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(redeye_output, "LOCK_WAIT_SECONDS", 0.3, raising=False)
    release, paused = threading.Event(), threading.Event()
    real, errors = os.replace, {}

    def pausing(*args, **kwargs):
        real(*args, **kwargs)
        if threading.current_thread().name == "A" and not paused.is_set():
            paused.set()
            assert release.wait(10)

    monkeypatch.setattr(redeye_output.os, "replace", pausing)

    def run(label):
        files = {"report.json": label, "summary.md": label, "perf.json": label}
        try:
            write_outputs(out, files)
        except ManifestError as error:
            errors[label] = error

    first = threading.Thread(target=run, args=("A",), name="A")
    first.start()
    assert paused.wait(10)
    second = threading.Thread(target=run, args=("B",), name="B")
    second.start()
    second.join(10)
    release.set()
    first.join(10)
    contents = {p.name: p.read_text() for p in out.iterdir() if p.name != ".write.lock"}
    assert sorted(contents) == ["perf.json", "report.json", "summary.md"]
    assert len(set(contents.values())) == 1, contents
    assert "B" in errors  # refused with a clear error rather than interleaved


# --- finding 5: a refused path leaves nothing behind --------------------------------------


def test_a_parent_swapped_for_a_symlink_to_the_corpus_leaves_no_directory(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "new" / "results"
    parent.rename(tmp_path / "aside")
    parent.symlink_to(corpus)
    with pytest.raises(ManifestError):
        write_outputs(target, {"report.json": "X"}, forbidden=[corpus])
    assert list(corpus.iterdir()) == []


def test_directories_created_before_a_rejection_are_removed_again(tmp_path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(ManifestError):
        write_outputs(base / "new" / "results", {"report.json": "X"}, forbidden=[base / "new"])
    assert list(base.iterdir()) == []


def test_report_json_is_replaced_last_and_a_removed_directory_is_refused(
    tmp_path, monkeypatch
) -> None:
    out = tmp_path / "out"
    names, real = [], os.replace

    def recording(src, dst, **kwargs):
        names.append(dst)
        real(src, dst, **kwargs)

    monkeypatch.setattr(redeye_output.os, "replace", recording)
    write_outputs(out, {"report.json": "R", "summary.md": "S", "perf.json": "P"})
    assert names[-1] == "report.json"
    assert sorted(names) == ["perf.json", "report.json", "summary.md"]


def test_a_directory_removed_while_writing_is_refused(tmp_path, monkeypatch) -> None:
    out = tmp_path / "out"
    real = redeye_output._acquire_lock

    def removing(fd):
        lock = real(fd)
        (out / redeye_output.LOCK_NAME).unlink()
        out.rmdir()
        return lock

    monkeypatch.setattr(redeye_output, "_acquire_lock", removing)
    with pytest.raises(ManifestError):
        write_outputs(out, {"report.json": "R"})
