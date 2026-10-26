"""The derived held-out split, declared-split refusal and leakage between splits."""

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.evaluation.redeye_manifest import ManifestError, load_manifest, parse_manifest
from fastfoto_linux.evaluation.redeye_run import run_eval
from fastfoto_linux.evaluation.redeye_split import (
    HELDOUT_PERCENT,
    Fingerprint,
    check_declared_splits,
    derived_split,
    find_leaks,
    pixel_digest,
)
from tests.redeye_eval.synth import (
    SALT,
    KeyedDetector,
    SynthItem,
    manifest_dict,
    positive,
    write_corpus,
)

PINNED = [
    ("0123456789abcdef", "a" * 64, "tuning"),
    ("0123456789abcdef", "d" * 64, "heldout"),
    ("00ff00ff00ff00ff", "3" * 64, "heldout"),
]


def test_heldout_share_is_twenty_percent() -> None:
    assert HELDOUT_PERCENT == 20


@pytest.mark.parametrize(("salt", "sha", "expected"), PINNED)
def test_derived_split_is_pinned(salt, sha, expected) -> None:
    assert derived_split(salt, None, sha) == expected
    assert derived_split(salt, None, sha) == derived_split(salt, None, sha)


def test_a_group_decides_instead_of_the_hash() -> None:
    assert derived_split(SALT, "print-7", "a" * 64) == derived_split(SALT, "print-7", "f" * 64)


def test_the_salt_matters() -> None:
    splits = {derived_split(f"{i:016x}", None, "d" * 64) for i in range(40)}
    assert splits == {"tuning", "heldout"}


def test_a_declared_split_that_disagrees_is_refused() -> None:
    data = manifest_dict([positive("a")], default="tuning")
    tmp = Path("/x")
    manifest = parse_manifest(json.dumps(data).encode(), tmp)
    derived = derived_split(SALT, None, manifest.images[0].sha256)
    wrong = "heldout" if derived == "tuning" else "tuning"
    data["images"][0]["split"] = derived
    check_declared_splits(parse_manifest(json.dumps(data).encode(), tmp))
    data["images"][0]["split"] = wrong
    with pytest.raises(ManifestError, match="split"):
        check_declared_splits(parse_manifest(json.dumps(data).encode(), tmp))


_UNSET = object()


def _fp(id_, sha=_UNSET, pixel=_UNSET, group=None) -> Fingerprint:
    return Fingerprint(
        id_,
        id_ * 64 if sha is _UNSET else sha,
        id_.upper() * 64 if pixel is _UNSET else pixel,
        group,
    )


def test_leaks_by_hash_pixels_group_and_id() -> None:
    held = [_fp("h", "a" * 64, "b" * 64, "g")]
    assert find_leaks(held, [_fp("t")]) == []
    assert any("file" in m for m in find_leaks(held, [_fp("t", sha="a" * 64)]))
    assert any("pixel" in m for m in find_leaks(held, [_fp("t", pixel="b" * 64)]))
    assert any("group" in m for m in find_leaks(held, [_fp("t", group="g")]))
    assert any("id" in m for m in find_leaks(held, [_fp("h")]))
    assert find_leaks([_fp("h", pixel=None)], [_fp("t", pixel=None)]) == []


def test_the_pixel_digest_ignores_png_compression() -> None:
    arr = positive("a").arr
    one, two = io.BytesIO(), io.BytesIO()
    Image.fromarray(arr).save(one, format="PNG", compress_level=0)
    Image.fromarray(arr).save(two, format="PNG", compress_level=9)
    assert one.getvalue() != two.getvalue()
    decoded = [np.asarray(Image.open(io.BytesIO(b.getvalue()))) for b in (one, two)]
    assert pixel_digest(decoded[0]) == pixel_digest(decoded[1])
    assert pixel_digest(arr) != pixel_digest(arr[:-1])


def _two_splits(tmp_path, held: SynthItem, tune: SynthItem, **kw):
    path = write_corpus(
        tmp_path / "c", [held, tune], splits={held.id: "heldout", tune.id: "tuning"}, **kw
    )
    return load_manifest(path)


def test_a_heldout_item_sharing_a_group_with_tuning_is_refused(tmp_path) -> None:
    held = positive("held")
    tune = positive("tune", centre=(150, 110))
    held.group = tune.group = "same-print"
    manifest = _two_splits(tmp_path, held, tune)
    with pytest.raises(ManifestError, match="group"):
        run_eval(manifest, "heldout", detector=KeyedDetector([held, tune]), perf=False)


def test_a_heldout_item_with_the_pixels_of_a_tuning_item_is_refused(tmp_path) -> None:
    held = positive("held")
    tune = SynthItem("tune", held.arr.copy(), held.faces, [], held.detections)
    root = tmp_path / "c"
    root.mkdir()
    (root / "held.png").write_bytes(held.png())
    buffer = io.BytesIO()
    Image.fromarray(tune.arr).save(buffer, format="PNG", compress_level=9)
    (root / "tune.png").write_bytes(buffer.getvalue())
    data = manifest_dict([held, tune], splits={"held": "heldout", "tune": "tuning"})
    data["images"][1]["sha256"] = hashlib.sha256(buffer.getvalue()).hexdigest()
    assert data["images"][1]["sha256"] != data["images"][0]["sha256"]
    (root / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(ManifestError, match="pixel"):
        run_eval(
            load_manifest(root / "manifest.json"),
            "heldout",
            detector=KeyedDetector([held]),
            perf=False,
        )


def test_a_heldout_item_in_a_tuning_manifest_is_refused(tmp_path) -> None:
    held = positive("held")
    other = write_corpus(
        tmp_path / "t",
        [SynthItem("other", held.arr.copy(), [], [], [])],
        splits={"other": "tuning"},
    )
    main = write_corpus(tmp_path / "m", [held], splits={"held": "heldout"})
    with pytest.raises(ManifestError, match=r"pixel|file"):
        run_eval(
            load_manifest(main),
            "heldout",
            detector=KeyedDetector([held]),
            tuning_manifests=[load_manifest(other)],
            perf=False,
        )


def test_tuning_reports_may_overlap(tmp_path) -> None:
    held = positive("held")
    tune = positive("tune")
    tune.group = held.group = "same-print"
    manifest = _two_splits(tmp_path, held, tune)
    result = run_eval(manifest, "tuning", detector=KeyedDetector([held, tune]), perf=False)
    assert [r.id for r in result.results] == ["tune"]
