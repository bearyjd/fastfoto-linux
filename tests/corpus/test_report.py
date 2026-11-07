"""The metrics-only report: an allowlist shape check, counts, and no private strings."""

import json
from types import MappingProxyType

import numpy as np
import pytest

from fastfoto_linux.evaluation.corpus_manifest import CorpusError, load_corpus_manifest
from fastfoto_linux.evaluation.corpus_report import (
    FORBIDDEN_KEYS,
    REPORT_STRINGS,
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
EXPECTED_STRINGS = (
    "tuning", "heldout", "photo", "document", "pass", "fail", "abstain", "insufficient_data",
    "not_applicable",
)  # fmt: skip


def test_the_forbidden_key_set_has_every_expected_key() -> None:
    assert set(EXPECTED_FORBIDDEN) <= FORBIDDEN_KEYS


def test_the_report_string_enum_is_closed() -> None:
    assert frozenset(EXPECTED_STRINGS) == REPORT_STRINGS


@pytest.mark.parametrize("key", EXPECTED_FORBIDDEN)
def test_each_forbidden_key_is_refused_at_any_depth(key: str) -> None:
    with pytest.raises(CorpusError, match="key"):
        check_metrics_only({key: 1})
    with pytest.raises(CorpusError, match="key"):
        check_metrics_only({"ok": [{"deep": {key: 1}}]})


def test_forbidden_keys_are_compared_after_normalising() -> None:
    for key in ("ocrtext", "Ocr_Text", "pixels_"[:-1], "ground__truth"):
        with pytest.raises(CorpusError, match="key"):
            check_metrics_only({key: 1})


def test_plain_metrics_pass() -> None:
    check_metrics_only(
        {"cer": 0.12, "n": 3, "ok": True, "none": None, "bins": [1, 2.5, 3], "verdict": "pass"}
    )
    for value in EXPECTED_STRINGS:
        check_metrics_only({"m": value})


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
        "Jane.Doe",
        "Jane",
        "IMG_1234",
        "x" * 64,
        "",
        "PASS",
        "café",
        float("nan"),
        float("inf"),
        10**4000,
        2**53,
        -(2**53),
        object(),
    ],
)
def test_non_metric_leaves_are_refused(bad: object) -> None:
    with pytest.raises(CorpusError):
        check_metrics_only({"m": bad})
    with pytest.raises(CorpusError):
        check_metrics_only([bad])


def test_integers_just_inside_the_bound_pass() -> None:
    check_metrics_only({"m": [2**53 - 1, -(2**53 - 1)]})


@pytest.mark.parametrize(
    "probe",
    [
        {"patient": "Jane.Doe"},
        {"IMG_1234": 0.4},
        {"img_1234_x": 0.4, "Jane": 1},
        {"recognized": ["Jane", "Doe"]},
        {"count": 10**4000},
        {"m": "someone@example.org"},
    ],
)
def test_the_known_leaks_are_refused(probe: dict) -> None:
    with pytest.raises(CorpusError):
        check_metrics_only(probe)


@pytest.mark.parametrize("key", ["has space", "", "x" * 49, 3, None, "a/b", "Upper", "1abc", "_x"])
def test_keys_must_be_short_lowercase_names(key: object) -> None:
    with pytest.raises(CorpusError):
        check_metrics_only({key: 1})


def test_a_key_of_48_characters_is_accepted() -> None:
    check_metrics_only({"a" + "b" * 47: 1})


def test_dicts_are_capped_at_64_keys() -> None:
    check_metrics_only({f"k{n}": n for n in range(64)})
    with pytest.raises(CorpusError, match="keys"):
        check_metrics_only({f"k{n}": n for n in range(65)})


def test_list_length_is_capped_at_32() -> None:
    check_metrics_only({"m": [0] * 32})
    with pytest.raises(CorpusError, match="list"):
        check_metrics_only({"m": [0] * 33})


def test_depth_is_capped_at_eight() -> None:
    ok: object = 1
    for _ in range(8):
        ok = {"a": ok}
    check_metrics_only(ok)  # eight containers deep
    with pytest.raises(CorpusError, match="deep"):
        check_metrics_only({"a": ok})


def test_pixel_lists_cannot_ride_along_as_long_lists() -> None:
    with pytest.raises(CorpusError):
        check_metrics_only({"m": list(range(1000))})


SENTINELS = (
    "SENTINELOCR", "Jane", "jane", "Studio", "Example Road", "SENTINELPATH",
    "private", "SENTINELBYTES", "item-", ".bin", "SENTINELGROUP", "SENTINELNOTE",
)  # fmt: skip


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
                group="SENTINELGROUP",
                annotations={
                    "ocr": {"gt": "SENTINELOCR", "lines": ["SENTINELOCR"], "SENTINELNOTE": 1}
                },
            )
        )
    (tmp_path / "MANIFEST.json").write_bytes(encode(document(items)))
    return load_corpus_manifest(tmp_path / "MANIFEST.json")


def test_the_report_holds_counts_and_metrics_but_no_private_strings(tmp_path) -> None:
    with _loaded(tmp_path) as manifest:
        out = serialise_report(build_report(manifest, {"cer": 0.25, "verdict": "pass"}))
        digest = manifest.sha256
    text = out.decode()
    for sentinel in (*SENTINELS, sha(b"SENTINELBYTES-0123")):
        assert sentinel not in text
    report = json.loads(text)
    assert report["manifest_sha256"] == digest
    assert report["items"]["total"] == 2
    assert sum(report["items"]["by_split"].values()) == 2
    assert report["items"]["by_kind"] == {"document": 1, "photo": 1}
    assert report["metrics"] == {"cer": 0.25, "verdict": "pass"}
    assert report["format"] == "fastfoto-corpus-report" and report["version"] == 1


def test_counts_include_zero_for_every_option(tmp_path) -> None:
    (tmp_path / "MANIFEST.json").write_bytes(encode(document([raw_item()])))
    with load_corpus_manifest(tmp_path / "MANIFEST.json", verify=False) as manifest:
        items = build_report(manifest, {})["items"]
    assert set(items["by_kind"]) == {"photo", "document"} and items["by_kind"]["document"] == 0
    assert set(items["by_split"]) == {"tuning", "heldout"}
    assert sorted(items["by_split"].values()) == [0, 1]


@pytest.mark.parametrize(
    "metrics",
    [
        {"item-jane-doe-0": 1},
        {"ITEM-JANE-DOE-0": 1},
        {"m": "Item-Jane-Doe-0"},
        {"sentinelgroup": 1},
        {"sentinelpath": 1},
        {"m": ["sentinelpath.bin"]},
        {"b": 1},
        {"lines": 1},
        {"sentinelocr": 1},
        {"m": {"deep": ["SENTINELOCR"]}},
        {"sentinelnote": 1},
        {"m": "Jane Doe Studio, 12 Example Road"},
        {"CC0-1.0": 1},
    ],
)
def test_build_report_refuses_metrics_that_echo_the_manifest(tmp_path, metrics: dict) -> None:
    with _loaded(tmp_path) as manifest, pytest.raises(CorpusError, match="manifest"):
        build_report(manifest, metrics)


def test_the_top_level_annotation_name_is_not_private(tmp_path) -> None:
    with _loaded(tmp_path) as manifest:
        assert build_report(manifest, {"ocr": 1})["metrics"] == {"ocr": 1}


def test_serialisation_is_deterministic_sorted_and_ascii(tmp_path) -> None:
    with _loaded(tmp_path) as manifest:
        one = serialise_report(build_report(manifest, {"zeta": 1, "alpha": 2}))
        two = serialise_report(build_report(manifest, {"alpha": 2, "zeta": 1}))
    assert one == two
    assert one.endswith(b"}\n") and one.isascii()
    assert one.index(b'"alpha"') < one.index(b'"zeta"')
    assert b"\n  " in one  # indented


def test_serialise_refuses_unsafe_metrics_before_writing(tmp_path) -> None:
    with _loaded(tmp_path) as manifest:
        for metrics in ({"pixels": [1]}, {"m": "two words"}, {"m": b"x"}, {"m": float("nan")}):
            with pytest.raises(CorpusError):
                serialise_report(build_report(manifest, metrics))


def test_serialise_refuses_a_tampered_envelope(tmp_path) -> None:
    with _loaded(tmp_path) as manifest:
        report = build_report(manifest, {})
    for tamper in ({"manifest_sha256": "Jane Doe"}, {"format": "x"}, {"extra": 1}):
        with pytest.raises(CorpusError):
            serialise_report({**report, **tamper})


def test_the_report_does_not_alias_the_callers_metrics(tmp_path) -> None:
    metrics: dict = {"scores": {}}
    with _loaded(tmp_path) as manifest:
        report = build_report(manifest, metrics)
    metrics["scores"]["sentinelpath"] = 1  # added after the echo check ran
    assert b"sentinelpath" not in serialise_report(report)


@pytest.mark.timeout(5)
def test_cyclic_metrics_are_refused_not_walked_forever(tmp_path) -> None:
    metrics: dict = {}
    metrics["scores"] = metrics
    with _loaded(tmp_path) as manifest, pytest.raises(CorpusError):
        build_report(manifest, metrics)


def test_read_only_mappings_are_accepted_as_metrics(tmp_path) -> None:
    metrics = MappingProxyType({"cer": 0.25, "by": MappingProxyType({"wer": 0.5})})
    with _loaded(tmp_path) as manifest:
        report = build_report(manifest, metrics)
    assert report["metrics"] == {"cer": 0.25, "by": {"wer": 0.5}}
