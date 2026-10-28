"""Fourth review pass: a pinned corpus root, containment of the output directory, a bounded
multi-frame check and no directories left behind by a refused path. (The per-replace and lock
tests of this pass went with the replace-based writer; see test_fifth_output.py.)"""

import io
import struct
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


# --- finding 1: the output directory is checked by identity before it is used -----------------


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
    _checkout(base / "new")  # the directories made inside it are refused as they appear
    with pytest.raises(ManifestError):
        write_outputs(base / "new" / "sub" / "results", {"report.json": "X"})
    assert sorted(p.name for p in (base / "new").iterdir()) == [".git", "pyproject.toml"]
