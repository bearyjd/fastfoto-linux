"""The metrics-only report: shape check, counts, and no private strings."""

import json

import numpy as np
import pytest

from fastfoto_linux.evaluation.corpus_manifest import CorpusError, load_corpus_manifest
from fastfoto_linux.evaluation.corpus_report import (
    FORBIDDEN_KEYS,
    build_report,
    check_metrics_only,
    serialise_report,
)
from tests.corpus.helpers import document, encode, raw_item, sha

EXPECTED_FORBIDDEN = (
    "pixels", "pixel", "image", "images", "crop", "crops", "thumbnail", "thumbnails",
    "text", "ocr_text", "path", "paths", "source", "licence", "filename", "name",
    "id", "ids", "bytes", "data", "ground_truth", "annotations",
)  # fmt: skip


def test_the_forbidden_key_set_has_every_expected_key() -> None:
    assert set(EXPECTED_FORBIDDEN) <= FORBIDDEN_KEYS


@pytest.mark.parametrize("key", EXPECTED_FORBIDDEN)
def test_each_forbidden_key_is_refused_at_any_depth(key: str) -> None:
    with pytest.raises(CorpusError, match="key"):
        check_metrics_only({key: 1})
    with pytest.raises(CorpusError, match="key"):
        check_metrics_only({"ok": [{"deep": {key.upper(): 1}}]})


def test_plain_metrics_pass() -> None:
    check_metrics_only(
        {"cer": 0.12, "n": 3, "ok": True, "none": None, "bins": [1, 2.5, 3], "tag": "v1.2:a+b-c_d"}
    )


@pytest.mark.parametrize(
    "bad",
    [
        b"raw",
        bytearray(b"x"),
        np.zeros(3),
        {1, 2},
        "has space",
        "line\nbreak",
        "a sentence of OCR text",
        "/home/someone/photo.png",
        "x" * 65,
        "",
        "café",
        float("nan"),
        float("inf"),
        object(),
    ],
)
def test_non_metric_leaves_are_refused(bad: object) -> None:
    with pytest.raises(CorpusError):
        check_metrics_only({"m": bad})
    with pytest.raises(CorpusError):
        check_metrics_only([bad])


def test_a_token_of_64_characters_is_accepted() -> None:
    check_metrics_only({"m": "x" * 64})


@pytest.mark.parametrize("key", ["has space", "", "x" * 65, 3, None, "a/b"])
def test_keys_must_be_tokens(key: object) -> None:
    with pytest.raises(CorpusError):
        check_metrics_only({key: 1})


def test_list_length_is_capped_at_32() -> None:
    check_metrics_only({"m": [0] * 32})
    with pytest.raises(CorpusError, match="list"):
        check_metrics_only({"m": [0] * 33})


def test_depth_is_capped_at_eight() -> None:
    ok: object = 1
    for _ in range(7):
        ok = {"a": ok}
    check_metrics_only(ok)  # eight containers deep
    with pytest.raises(CorpusError, match="deep"):
        check_metrics_only({"a": ok})


def test_pixel_lists_cannot_ride_along_as_long_lists() -> None:
    with pytest.raises(CorpusError):
        check_metrics_only({"m": list(range(1000))})


def _loaded(tmp_path):
    files = {"private/SENTINELPATH.bin": b"SENTINELBYTES-0123", "b.bin": b"beta"}
    items = []
    for number, (rel, data) in enumerate(files.items()):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        items.append(
            raw_item(
                f"jane-doe-{number}",
                data,
                path=rel,
                kind="document" if number else "photo",
                source="Jane Doe Studio, 12 Example Road",
                annotations={"ocr": {"gt": "SENTINELOCR", "lines": ["SENTINELOCR"]}},
            )
        )
    (tmp_path / "MANIFEST.json").write_bytes(encode(document(items)))
    return load_corpus_manifest(tmp_path / "MANIFEST.json")


def test_the_report_holds_counts_and_metrics_but_no_private_strings(tmp_path) -> None:
    with _loaded(tmp_path) as manifest:
        out = serialise_report(build_report(manifest, {"cer": 0.25, "tag": "run1"}))
        digest = manifest.sha256
    text = out.decode()
    for sentinel in ("SENTINELOCR", "Jane", "jane", "Studio", "Example Road", "SENTINELPATH",
                     "private", "SENTINELBYTES", "item-", sha(b"SENTINELBYTES-0123"), ".bin"):  # fmt: skip
        assert sentinel not in text
    report = json.loads(text)
    assert report["manifest_sha256"] == digest
    assert report["items"]["total"] == 2
    assert sum(report["items"]["by_split"].values()) == 2
    assert report["items"]["by_kind"] == {"document": 1, "photo": 1}
    assert report["metrics"] == {"cer": 0.25, "tag": "run1"}
    assert report["format"] == "fastfoto-corpus-report" and report["version"] == 1


def test_serialisation_is_deterministic_sorted_and_ascii(tmp_path) -> None:
    with _loaded(tmp_path) as manifest:
        one = serialise_report(build_report(manifest, {"b": 1, "a": 2}))
        two = serialise_report(build_report(manifest, {"a": 2, "b": 1}))
    assert one == two
    assert one.endswith(b"}\n") and one.isascii()
    assert one.index(b'"a"') < one.index(b'"b"')
    assert b"\n  " in one  # indented


def test_serialise_refuses_unsafe_metrics_before_writing(tmp_path) -> None:
    with _loaded(tmp_path) as manifest:
        for metrics in ({"pixels": [1]}, {"m": "two words"}, {"m": b"x"}, {"m": float("nan")}):
            with pytest.raises(CorpusError):
                serialise_report(build_report(manifest, metrics))
