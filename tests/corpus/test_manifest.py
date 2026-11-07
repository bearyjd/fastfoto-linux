"""Corpus manifest parsing: strict keys, rights, hashes, annotations, splits."""

import json
from types import MappingProxyType

import pytest

from fastfoto_linux.evaluation import corpus_manifest
from fastfoto_linux.evaluation.corpus_manifest import (
    MAX_ANNOTATION_NODES,
    CorpusError,
    assign_splits,
    load_corpus_manifest,
    parse_corpus_manifest,
)
from fastfoto_linux.evaluation.redeye_split import derived_split
from tests.corpus.helpers import SEED, document, encode, manifest_bytes, raw_item, sha, unsplit


def _parse(*items: dict):
    return parse_corpus_manifest(manifest_bytes(*items))


def test_a_valid_manifest_parses() -> None:
    data = manifest_bytes(raw_item("a", group="print-1"), raw_item("b", b"beta", kind="document"))
    manifest = parse_corpus_manifest(data)
    assert manifest.split_seed == SEED
    assert [i.id for i in manifest.items] == ["item-a", "item-b"]
    assert manifest.items[0].group == "print-1" and manifest.items[1].group is None
    assert manifest.items[1].kind == "document"
    assert manifest.sha256 == sha(data)


@pytest.mark.parametrize("field", ["source", "licence", "consent_scope"])
def test_each_missing_rights_field_is_refused_by_name(field: str) -> None:
    item = raw_item()
    del item[field]
    with pytest.raises(CorpusError, match=field):
        _parse(item)


@pytest.mark.parametrize("field", ["id", "path", "sha256", "kind", "split", "annotations"])
def test_other_missing_fields_are_refused_by_name(field: str) -> None:
    item = raw_item()
    del item[field]
    with pytest.raises(CorpusError, match=field):
        _parse(item)


@pytest.mark.parametrize("field", ["source", "licence"])
@pytest.mark.parametrize("value", ["", "   ", "x" * 513, 7, None])
def test_bad_rights_text_is_refused(field: str, value: object) -> None:
    with pytest.raises(CorpusError, match=field):
        _parse(raw_item(**{field: value}))


def test_rights_text_of_512_characters_is_accepted() -> None:
    assert _parse(raw_item(licence="x" * 512)).items[0].licence == "x" * 512


@pytest.mark.parametrize("value", ["public", "", None, True, "Private-Eval"])
def test_unknown_consent_scope_is_refused(value: object) -> None:
    with pytest.raises(CorpusError, match="consent_scope"):
        _parse(raw_item(consent_scope=value))


def test_redistributable_consent_scope_is_accepted() -> None:
    item = _parse(raw_item(consent_scope="redistributable")).items[0]
    assert item.consent_scope == "redistributable"


@pytest.mark.parametrize(
    "bad", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", " " + "a" * 63, "a" * 64 + "\n", 5]
)
def test_malformed_sha256_is_refused(bad: object) -> None:
    with pytest.raises(CorpusError, match="sha256"):
        _parse(raw_item(sha256=bad, split="tuning"))


def test_unknown_keys_are_refused() -> None:
    with pytest.raises(CorpusError, match="unknown"):
        _parse(raw_item(extra=1))
    doc = document([raw_item()])
    doc["extra"] = 1
    with pytest.raises(CorpusError, match="unknown"):
        parse_corpus_manifest(encode(doc))


def test_a_nested_rights_object_is_not_the_format() -> None:
    with pytest.raises(CorpusError):
        _parse(raw_item(rights={"source": "x"}))


def test_duplicate_keys_nan_and_garbage_are_refused() -> None:
    good = manifest_bytes(raw_item()).decode()
    with pytest.raises(CorpusError, match="duplicate"):
        parse_corpus_manifest(good.replace('"kind"', '"kind": "photo", "kind"').encode())
    nan = good.replace('"annotations": {}', '"annotations": {"a": {"x": NaN}}')
    for text in (nan, "{", "[]", ""):
        with pytest.raises(CorpusError):
            parse_corpus_manifest(text.encode())
    with pytest.raises(CorpusError):
        _parse(raw_item(annotations={"a": {"x": 1e999}}))


@pytest.mark.parametrize(
    "fmt, version", [("other", 1), ("fastfoto-corpus", 2), ("fastfoto-corpus", True)]
)
def test_format_and_version_are_checked(fmt: str, version: object) -> None:
    doc = document([raw_item()])
    doc["format"], doc["version"] = fmt, version
    with pytest.raises(CorpusError):
        parse_corpus_manifest(encode(doc))


def test_bad_ids_paths_kinds_and_groups_are_refused() -> None:
    for over in (
        {"id": "has space"},
        {"id": "a" * 129},
        {"id": ""},
        {"group": "bad group"},
        {"kind": "video"},
        {"split": "validation"},
        {"path": "../x.bin"},
        {"path": "/abs.bin"},
        {"path": "a//b.bin"},
        {"path": "a\\b.bin"},
        {"path": "./a.bin"},
    ):
        with pytest.raises(CorpusError):
            _parse(raw_item(**over))


def test_ids_hashes_and_paths_must_be_unique() -> None:
    a = raw_item("a")
    for clash in (
        raw_item("b", b"beta", id=a["id"]),
        raw_item("b", b"alpha"),
        raw_item("b", b"beta", path=a["path"]),
    ):
        with pytest.raises(CorpusError, match="duplicate"):
            _parse(a, clash)


def test_annotations_are_deeply_immutable() -> None:
    item = _parse(raw_item(annotations={"deskew": {"angle": 1.5, "pts": [1, [2, 3]]}})).items[0]
    assert isinstance(item.annotations, MappingProxyType)
    inner = item.annotations["deskew"]
    assert isinstance(inner, MappingProxyType)
    assert inner["pts"] == (1, (2, 3))
    with pytest.raises(TypeError):
        item.annotations["x"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        inner["angle"] = 0  # type: ignore[index]


def test_annotation_shape_is_checked() -> None:
    for bad in ([], {"Bad": {}}, {"1a": {}}, {"a" * 33: {}}, {"a": 1}, {"a": []}, "x"):
        with pytest.raises(CorpusError):
            _parse(raw_item(annotations=bad))
    assert _parse(raw_item(annotations={"a" * 32: {}, "a_1": {}})).items[0].annotations.keys()


def _nested(levels: int) -> dict:
    value: dict = {}
    for _ in range(levels - 1):
        value = {"n": value}
    return value


def test_annotation_depth_is_capped_at_eight_levels() -> None:
    assert _parse(raw_item(annotations={"a": _nested(7)}))
    with pytest.raises(CorpusError, match="deep"):
        _parse(raw_item(annotations={"a": _nested(8)}))


def test_hostile_nesting_is_a_corpus_error_not_a_recursion_error() -> None:
    text = '{"format": "x", "items": ' + "[" * 100_000 + "]" * 100_000 + "}"
    with pytest.raises(CorpusError):
        parse_corpus_manifest(text.encode())


def test_annotation_node_count_is_capped() -> None:
    fill = MAX_ANNOTATION_NODES - 3  # the object, one value object and the list are nodes too
    assert _parse(raw_item(annotations={"a": {"v": [0] * fill}}))
    with pytest.raises(CorpusError, match="large"):
        _parse(raw_item(annotations={"a": {"v": [0] * (fill + 1)}}))


def test_an_oversized_manifest_file_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(corpus_manifest, "MAX_MANIFEST_BYTES", 100)
    path = tmp_path / "MANIFEST.json"
    path.write_bytes(manifest_bytes(raw_item()))
    with pytest.raises(CorpusError, match="large"):
        load_corpus_manifest(path, verify=False)


def test_a_declared_split_that_differs_from_the_derived_one_is_refused() -> None:
    item = raw_item()
    flipped = "heldout" if item["split"] == "tuning" else "tuning"
    with pytest.raises(CorpusError, match="split"):
        _parse({**item, "split": flipped})


def test_the_split_rule_is_the_red_eye_rule_and_deterministic() -> None:
    items = [raw_item(str(n), str(n).encode()) for n in range(60)]
    for item in items:
        assert item["split"] == derived_split(SEED, None, item["sha256"])
    stripped = [unsplit(i) for i in items]
    first, second = assign_splits(stripped, SEED), assign_splits(stripped, SEED)
    assert first == second == items
    assert all("split" not in i for i in stripped)  # the input is not changed
    heldout = sum(i["split"] == "heldout" for i in first)
    assert 3 <= heldout <= 25  # about 20 % of 60


def test_a_different_seed_gives_a_different_assignment() -> None:
    stripped = [unsplit(raw_item(str(n), str(n).encode())) for n in range(60)]
    other = assign_splits(stripped, "f" * 32)
    assert [i["split"] for i in other] != [i["split"] for i in assign_splits(stripped, SEED)]


def test_a_group_shares_one_split_whatever_the_hashes() -> None:
    stripped = [unsplit(raw_item(str(n), str(n).encode(), group="print-7")) for n in range(20)]
    assert len({i["split"] for i in assign_splits(stripped, SEED)}) == 1


def test_assign_splits_refuses_a_bad_seed_or_hash() -> None:
    with pytest.raises(CorpusError):
        assign_splits([raw_item()], "XYZ")
    with pytest.raises(CorpusError):
        assign_splits([raw_item(sha256="nope")], SEED)


def test_the_manifest_is_a_context_manager_and_close_is_idempotent(tmp_path) -> None:
    (tmp_path / "MANIFEST.json").write_bytes(manifest_bytes(raw_item()))
    with load_corpus_manifest(tmp_path / "MANIFEST.json", verify=False) as manifest:
        assert manifest.root_fd is not None
    manifest.close()
    assert manifest.root_fd is None
    json.loads(manifest_bytes(raw_item()))
