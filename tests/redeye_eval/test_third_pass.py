"""Third review pass: no path races, a late output swap is refused, hostile decoders and numbers."""

import io
import json
import os
import struct
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.cli import cmd_eval, main
from fastfoto_linux.evaluation import redeye_images
from fastfoto_linux.evaluation.redeye_images import ImageError, decode_image, read_contained
from fastfoto_linux.evaluation.redeye_manifest import (
    ManifestError,
    Region,
    load_manifest,
    parse_manifest,
)
from fastfoto_linux.evaluation.redeye_match import count_changes
from fastfoto_linux.evaluation.redeye_output import resolve_out_dir, write_outputs
from tests.redeye_eval.synth import (
    KeyedDetector,
    clean_heldout_set,
    manifest_dict,
    positive,
    write_corpus,
)

pytestmark = pytest.mark.usefixtures("outside_checkout")


def test_an_ancestor_swapped_for_a_symlink_before_the_open_never_reads_outside(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "corpus"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "file").write_bytes(b"INSIDE")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"OUTSIDE SECRET")
    real_open, swapped = os.open, []

    def racing_open(path, *args, **kwargs):
        if not swapped and Path(os.fsdecode(path)) != root.resolve():
            swapped.append(1)
            (root / "sub").rename(tmp_path / "moved")
            (root / "sub").symlink_to(outside)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(redeye_images.os, "open", racing_open)
    try:
        data = read_contained(root, "sub/file")
    except ImageError:
        return
    assert data != b"OUTSIDE SECRET"


def test_a_symlinked_ancestor_directory_is_refused(tmp_path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.png").write_bytes(b"x")
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "dir").symlink_to(tmp_path / "real")
    with pytest.raises(ImageError):
        read_contained(root, "dir/a.png")


def _swapped_out(tmp_path):
    manifest = load_manifest(write_corpus(tmp_path / "corpus", [positive("a")]))
    (tmp_path / "corpus" / "report.json").write_text("CORPUS")
    out = resolve_out_dir(manifest, tmp_path / "results", {})
    out.symlink_to(manifest.root)  # swapped in after validation
    return manifest, out


def test_an_output_dir_swapped_for_a_symlink_to_the_corpus_is_refused(tmp_path) -> None:
    manifest, out = _swapped_out(tmp_path)
    with pytest.raises(ManifestError):
        write_outputs(out, {"report.json": "REPLACED"}, forbidden=[manifest.root])
    assert (manifest.root / "report.json").read_text() == "CORPUS"


def test_an_output_path_through_a_symlinked_parent_into_the_corpus_is_refused(tmp_path) -> None:
    manifest = load_manifest(write_corpus(tmp_path / "corpus", [positive("a")]))
    (tmp_path / "corpus" / "report.json").write_text("CORPUS")
    (tmp_path / "link").symlink_to(manifest.root)
    with pytest.raises(ManifestError):
        write_outputs(tmp_path / "link", {"report.json": "REPLACED"}, forbidden=[manifest.root])
    assert (manifest.root / "report.json").read_text() == "CORPUS"


def test_a_malformed_tiff_is_a_corrupt_image_not_a_crash() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 9)).save(buffer, "TIFF")
    data = bytearray(buffer.getvalue())
    struct.pack_into("<I", data, 130, len(data))
    with pytest.raises(ImageError) as info:
        decode_image(bytes(data))
    assert info.value.code == "corrupt"


def test_a_lone_surrogate_path_is_refused_by_the_manifest_and_the_loader(tmp_path) -> None:
    data = manifest_dict([positive("a")], default="tuning")
    text = json.dumps(data).replace('"a.png"', '"\\ud800.png"')
    with pytest.raises(ManifestError):
        parse_manifest(text.encode(), tmp_path)
    with pytest.raises(ImageError) as info:
        read_contained(tmp_path, "\ud800.png")
    assert info.value.code == "unreadable"


def test_a_fifo_named_pyproject_toml_does_not_hang_the_checkout_check(tmp_path) -> None:
    manifest = load_manifest(write_corpus(tmp_path / "corpus", [positive("a")]))
    fake = tmp_path / "fake"
    (fake / ".git").mkdir(parents=True)
    os.mkfifo(fake / "pyproject.toml")
    outcome = []

    def run() -> None:
        outcome.append(resolve_out_dir(manifest, fake / "results", {}))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(3)
    assert not thread.is_alive(), "the checkout check blocked on a FIFO"


def test_a_no_perf_rerun_removes_the_stale_perf_json(tmp_path, monkeypatch) -> None:
    items = clean_heldout_set()
    path = write_corpus(tmp_path / "c", items)
    monkeypatch.setattr(cmd_eval, "make_detector", lambda: KeyedDetector(items))
    out = tmp_path / "r"
    assert main(["eval", "redeye", str(path), "--out", str(out)]) == 0
    assert (out / "perf.json").exists()
    assert main(["eval", "redeye", str(path), "--out", str(out), "--no-perf"]) == 0
    assert not (out / "perf.json").exists()


@pytest.mark.parametrize("field", ["x", "y", "r"])
def test_enormous_integers_are_a_manifest_error_not_an_overflow(field, tmp_path) -> None:
    data = manifest_dict([positive("a")], default="tuning")
    data["images"][0]["faces"][0]["eyes"][0][field] = 10**400
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps(data).encode(), tmp_path)


def test_a_change_outside_every_box_is_attributed_to_all_categories() -> None:
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    out = img.copy()
    out[30, 30] = 9
    boxes = [Region("lips", (0, 0, 5, 5)), Region("red_clothing", (10, 10, 15, 15))]
    counts = count_changes(img, out, [], [], boxes, negative_image=True)
    assert counts.damaged_categories == ("lips", "red_clothing")
    assert count_changes(img, out, [], [], [], negative_image=True).damaged_categories == ("other",)
