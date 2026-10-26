"""Hostile paths, hostile images and hostile output directories."""

import hashlib
import io
import os
import re
import struct
import tracemalloc
import zlib
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.evaluation import redeye_images, redeye_output
from fastfoto_linux.evaluation.redeye_images import ImageError, load_image, read_contained
from fastfoto_linux.evaluation.redeye_manifest import ManifestError, check_relpath, load_manifest
from fastfoto_linux.evaluation.redeye_output import resolve_out_dir, write_outputs
from tests.redeye_eval.synth import positive, write_corpus

SRC = Path(__file__).resolve().parents[2] / "src" / "fastfoto_linux" / "evaluation"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _code(root: Path, rel: str, sha: str) -> str:
    with pytest.raises(ImageError) as info:
        load_image(root, rel, sha)
    return info.value.code


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def test_unsafe_relative_paths_are_refused() -> None:
    for bad in ("../x.png", "/etc/x", "a\\b.png", "a/../b.png", "a//b.png", "./a.png", "", "a\0b"):
        with pytest.raises(ManifestError):
            check_relpath(bad)
    check_relpath("sub/dir/ok.png")


def test_a_symlink_leaving_the_root_is_refused(tmp_path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.png").symlink_to(outside)
    with pytest.raises(ImageError) as info:
        read_contained(root, "link.png")
    assert info.value.code == "unsafe_path"


def test_a_symlinked_directory_leaving_the_root_is_refused(tmp_path) -> None:
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "a.png").write_bytes(b"x")
    root = tmp_path / "root"
    root.mkdir()
    (root / "dir").symlink_to(tmp_path / "other")
    with pytest.raises(ImageError) as info:
        read_contained(root, "dir/a.png")
    assert info.value.code == "unsafe_path"


def test_a_symlink_inside_the_root_is_followed_and_contained(tmp_path) -> None:
    (tmp_path / "real.png").write_bytes(b"data")
    (tmp_path / "alias.png").symlink_to(tmp_path / "real.png")
    assert read_contained(tmp_path, "alias.png") == b"data"


def test_a_fifo_is_refused_without_blocking(tmp_path) -> None:
    os.mkfifo(tmp_path / "pipe.png")
    with pytest.raises(ImageError) as info:
        read_contained(tmp_path, "pipe.png")
    assert info.value.code == "unsafe_path"


def test_missing_corrupt_and_mismatched_images(tmp_path) -> None:
    item = positive("a")
    data = item.png()
    (tmp_path / "ok.png").write_bytes(data)
    (tmp_path / "cut.png").write_bytes(data[: len(data) // 2])
    assert _code(tmp_path, "nope.png", "0" * 64) == "missing"
    assert _code(tmp_path, "cut.png", _sha(data[: len(data) // 2])) == "corrupt"
    assert _code(tmp_path, "ok.png", "0" * 64) == "hash_mismatch"
    assert load_image(tmp_path, "ok.png", _sha(data)).shape == item.arr.shape


def test_a_header_claiming_400_megapixels_is_too_large_without_allocating(tmp_path) -> None:
    header = struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
    assert len(data) == 33
    (tmp_path / "bomb.png").write_bytes(data)
    tracemalloc.start()
    try:
        code = _code(tmp_path, "bomb.png", _sha(data))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert code == "too_large"
    assert peak < 10_000_000


def test_the_pixel_cap_is_checked_on_the_header_before_loading(tmp_path, monkeypatch) -> None:
    item = positive("a")
    (tmp_path / "a.png").write_bytes(item.png())
    monkeypatch.setattr(
        redeye_images, "MAX_SOURCE_PIXELS", item.arr.shape[0] * item.arr.shape[1] - 1
    )
    assert _code(tmp_path, "a.png", item.sha256()) == "too_large"
    monkeypatch.setattr(redeye_images, "MAX_SOURCE_PIXELS", item.arr.shape[0] * item.arr.shape[1])
    assert load_image(tmp_path, "a.png", item.sha256()).shape == item.arr.shape


def test_the_byte_cap_is_enforced(tmp_path, monkeypatch) -> None:
    (tmp_path / "a.png").write_bytes(b"0123456789")
    monkeypatch.setattr(redeye_images, "MAX_SOURCE_BYTES", 9)
    assert _code(tmp_path, "a.png", "0" * 64) == "too_large"


def test_only_rgb_grey_and_opaque_palette_images_are_accepted(tmp_path) -> None:
    def save(name: str, image: Image.Image, **kwargs) -> tuple[str, str]:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", **kwargs)
        (tmp_path / name).write_bytes(buffer.getvalue())
        return name, _sha(buffer.getvalue())

    name, sha = save("l.png", Image.new("L", (8, 8), 90))
    assert load_image(tmp_path, name, sha).shape == (8, 8, 3)
    name, sha = save("p.png", Image.new("P", (8, 8), 1))
    assert load_image(tmp_path, name, sha).shape == (8, 8, 3)
    name, sha = save("rgba.png", Image.new("RGBA", (8, 8), (1, 2, 3, 4)))
    assert _code(tmp_path, name, sha) == "bad_mode"
    name, sha = save("pt.png", Image.new("P", (8, 8), 1), transparency=0)
    assert _code(tmp_path, name, sha) == "bad_mode"
    name, sha = save("i16.png", Image.new("I;16", (8, 8), 3))
    assert _code(tmp_path, name, sha) == "bad_mode"


def test_the_package_never_shells_out_or_uses_the_network() -> None:
    banned = re.compile(
        r"subprocess|os\.system|shell\s*=\s*True|socket|urllib|http\.client|requests"
    )
    hits = [p.name for p in SRC.glob("*.py") if banned.search(p.read_text())]
    assert hits == []


def test_out_dir_inside_the_manifest_root_is_refused(tmp_path) -> None:
    manifest = load_manifest(write_corpus(tmp_path / "corpus", [positive("a")]))
    for inside in (manifest.root, manifest.root / "results"):
        with pytest.raises(ManifestError, match="manifest"):
            resolve_out_dir(manifest, inside, {})


def test_out_dir_inside_a_project_checkout_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(redeye_output, "PROJECT_NAME", "fake-fastfoto")
    manifest = load_manifest(write_corpus(tmp_path / "corpus", [positive("a")]))
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text('[project]\nname = "fake-fastfoto"\n')
    with pytest.raises(ManifestError, match="checkout"):
        resolve_out_dir(manifest, checkout / "deep" / "results", {})
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    (other / "pyproject.toml").write_text('[project]\nname = "something-else"\n')
    assert resolve_out_dir(manifest, other / "results", {}) == other / "results"


def test_default_out_dir_is_in_the_cache_and_keyed_by_the_manifest_hash(
    tmp_path, outside_checkout
) -> None:
    manifest = load_manifest(write_corpus(tmp_path / "corpus", [positive("a")]))
    cache = tmp_path / "cache"
    expected = cache / "fastfoto-linux" / "redeye-eval" / manifest.sha256[:12]
    assert resolve_out_dir(manifest, None, {"XDG_CACHE_HOME": str(cache)}) == expected
    home = tmp_path / "home"
    fallback = resolve_out_dir(manifest, None, {"HOME": str(home)})
    assert fallback == home / ".cache" / "fastfoto-linux" / "redeye-eval" / manifest.sha256[:12]


def test_outputs_are_private_and_replaced_atomically(tmp_path) -> None:
    out = tmp_path / "out"
    write_outputs(out, {"report.json": "one\n"})
    write_outputs(out, {"report.json": "two\n"})
    assert (out / "report.json").read_text() == "two\n"
    assert (out.stat().st_mode & 0o777) == 0o700
    assert ((out / "report.json").stat().st_mode & 0o777) == 0o600
    assert sorted(p.name for p in out.iterdir()) == ["report.json"]
