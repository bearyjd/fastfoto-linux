"""The JSON Schema document stays in step with the loader; the example loads."""

import json
import re
from pathlib import Path

import pytest

from fastfoto_linux.evaluation import corpus_manifest as cm
from fastfoto_linux.evaluation.corpus_manifest import assign_splits, load_corpus_manifest

CORPUS = Path(__file__).resolve().parents[2] / "corpus"


def _schema() -> dict:
    return json.loads((CORPUS / "MANIFEST.schema.json").read_text())


def _item_schema() -> dict:
    return _schema()["properties"]["items"]["items"]


def test_top_level_constants_match() -> None:
    schema = _schema()
    props = schema["properties"]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert props["format"]["const"] == cm.FORMAT
    assert props["version"]["const"] == cm.VERSION
    assert props["split_seed"]["pattern"] == f"^{cm.SEED_PATTERN}$"
    assert set(schema["required"]) == set(props) == set(cm.TOP_KEYS)
    assert props["items"]["maxItems"] == cm.MAX_ITEMS
    assert schema["additionalProperties"] is False


def test_item_constants_match() -> None:
    item = _item_schema()
    props = item["properties"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(cm.ITEM_REQUIRED)
    assert set(props) == set(cm.ITEM_REQUIRED) | {"group"}
    assert props["id"]["pattern"] == props["group"]["pattern"] == f"^{cm.ID_PATTERN}$"
    assert props["sha256"]["pattern"] == f"^{cm.SHA_PATTERN}$"
    assert tuple(props["kind"]["enum"]) == cm.KINDS
    assert tuple(props["split"]["enum"]) == cm.SPLITS
    assert tuple(props["consent_scope"]["enum"]) == cm.CONSENT_SCOPES
    for name in ("source", "licence"):
        assert props[name]["minLength"] == 1 and props[name]["maxLength"] == cm.MAX_TEXT
    ann = props["annotations"]
    assert ann["type"] == "object"
    assert ann["propertyNames"]["pattern"] == f"^{cm.ANNOTATION_KEY_PATTERN}$"
    assert ann["additionalProperties"]["type"] == "object"


def test_the_schema_path_pattern_agrees_with_the_loader() -> None:
    pattern = re.compile(_item_schema()["properties"]["path"]["pattern"])
    for good in ("a.bin", "sub/dir/a.bin", ".hidden/x"):
        assert pattern.search(good)
    for bad in ("", "/abs", "../x", "a/../b", "a//b", "./a", "a/.", "a\\b", "a\0b"):
        assert not pattern.search(bad), bad
        with pytest.raises(cm.CorpusError):
            cm.check_relpath(bad)


def test_the_example_loads_and_its_splits_come_from_assign_splits() -> None:
    path = CORPUS / "MANIFEST.example.json"
    with load_corpus_manifest(path, verify=False) as manifest:
        assert len(manifest.items) == 2
    raw = json.loads(path.read_text())
    unsplit = [{k: v for k, v in i.items() if k != "split"} for i in raw["items"]]
    assert assign_splits(unsplit, raw["split_seed"]) == raw["items"]


def test_the_corpus_directory_holds_no_images() -> None:
    names = [p.name for p in CORPUS.rglob("*") if p.is_file()]
    assert names
    assert {Path(n).suffix for n in names} <= {".json", ".md"}
