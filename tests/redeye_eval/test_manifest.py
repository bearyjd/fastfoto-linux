"""Manifest parsing: every malformed shape is refused, an empty image list is allowed."""

import copy
import json
from pathlib import Path

import pytest

from fastfoto_linux.evaluation.redeye_manifest import (
    MAX_MANIFEST_BYTES,
    ManifestError,
    load_manifest,
    parse_manifest,
)
from tests.redeye_eval.synth import manifest_dict, negative, positive, write_corpus

ROOT = Path("/nonexistent-root")


def _base() -> dict:
    return manifest_dict([positive("a"), negative("b", "lips")], default="tuning")


def _parse(data) -> object:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return parse_manifest(raw, ROOT)


def _mutate(path: list, value) -> dict:
    data = copy.deepcopy(_base())
    target = data
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


def test_valid_manifest_parses() -> None:
    manifest = _parse(_base())
    assert [image.id for image in manifest.images] == ["a", "b"]
    assert manifest.images[0].faces[0].eyes[0].red is True
    assert len(manifest.sha256) == 64


@pytest.mark.parametrize(
    "bad",
    [
        _mutate(["extra"], 1),
        _mutate(["format"], "other"),
        _mutate(["version"], 2),
        _mutate(["split_salt"], "xyz"),
        _mutate(["images", 0, "extra"], 1),
        _mutate(["images", 0, "rights", "licence"], ""),
        _mutate(["images", 0, "rights", "licence"], KeyError),
        _mutate(["images", 0, "rights", "redistributable"], 1),
        _mutate(["images", 0, "upright"], False),
        _mutate(["images", 0, "upright"], KeyError),
        _mutate(["images", 0, "dpi"], True),
        _mutate(["images", 0, "dpi"], 49),
        _mutate(["images", 0, "dpi"], 2401),
        _mutate(["images", 0, "sha256"], "A" * 64),
        _mutate(["images", 0, "split"], "validation"),
        _mutate(["images", 0, "id"], "bad id!"),
        _mutate(["images", 0, "faces", 0, "eyes"], [{"x": 1.0, "y": 1.0, "r": 2.0, "red": True}]),
        _mutate(["images", 0, "faces", 0, "eyes", 0, "r"], 0),
        _mutate(["images", 0, "faces", 0, "eyes", 0, "red"], 1),
        _mutate(["images", 0, "faces", 0, "eyes", 0, "x"], True),
        _mutate(["images", 1, "negatives", 0, "category"], "cats"),
        _mutate(["images", 1, "negatives", 0, "box"], [5, 5, 5, 9]),
        _mutate(["images", 0, "path"], "../x.png"),
        _mutate(["images", 0, "path"], "/etc/x.png"),
        _mutate(["images", 0, "path"], "a\\b.png"),
        _mutate(["images", 0, "path"], "a//b.png"),
    ],
)
def test_malformed_manifests_are_refused(bad) -> None:
    with pytest.raises(ManifestError):
        _parse(bad)


def test_three_eyes_are_refused() -> None:
    data = _base()
    eyes = data["images"][0]["faces"][0]["eyes"]
    eyes.append(dict(eyes[0]))
    with pytest.raises(ManifestError):
        _parse(data)


def test_duplicate_id_and_duplicate_sha_are_refused() -> None:
    data = _base()
    data["images"][1]["id"] = "a"
    with pytest.raises(ManifestError, match="duplicate"):
        _parse(data)
    data = _base()
    data["images"][1]["sha256"] = data["images"][0]["sha256"]
    with pytest.raises(ManifestError, match="duplicate"):
        _parse(data)


def test_duplicate_json_key_nan_and_garbage_are_refused() -> None:
    text = json.dumps(_base())
    with pytest.raises(ManifestError):
        _parse(text.replace('"version": 1', '"version": 1, "version": 1').encode())
    with pytest.raises(ManifestError):
        _parse(text.replace('"r": 5.0', '"r": NaN', 1).encode())
    with pytest.raises(ManifestError):
        _parse(b"not json")
    with pytest.raises(ManifestError):
        _parse(b"[]")


def test_empty_image_list_is_accepted() -> None:
    data = _base()
    data["images"] = []
    assert _parse(data).images == ()


def test_load_manifest_reads_the_file_and_caps_its_size(tmp_path) -> None:
    path = write_corpus(tmp_path / "corpus", [positive("a")])
    manifest = load_manifest(path)
    assert manifest.root == path.parent.resolve()
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
    with pytest.raises(ManifestError, match="too large"):
        load_manifest(big)
    with pytest.raises(ManifestError, match="cannot read"):
        load_manifest(tmp_path / "missing.json")
