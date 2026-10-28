"""Sidecar format 6: written only for a deskew angle, read strictly, never granted to older files."""

import json
from dataclasses import replace
from typing import Any

import pytest

from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_edit import set_deskew, set_document_cleanup
from fastfoto_linux.documents.draft_json import ReviewFormatError, decode_review, encode_review
from fastfoto_linux.documents.modes import CleanupPolicy
from fastfoto_linux.documents.sidecar_versions import (
    DESKEW_VERSION,
    DESPECKLE_VERSION,
    FORMAT_VERSION,
    READ_VERSIONS,
)
from tests.documents.test_cleanup_sidecar import MAIN_BYTES, NAMES, plain
from tests.documents.test_crop_sidecar import cropped
from tests.documents.test_despeckle_sidecar import _old, on
from tests.documents.test_sidecar_despeckle_version import PINNED_V5

EDIT_KEYS_V6 = {"include", "turns", "colour", "cleanup", "crop", "deskew"}


def straight(draft: DocumentDraft | None = None) -> DocumentDraft:
    return set_deskew(plain() if draft is None else draft, 2, -27)


def v6() -> dict[str, Any]:
    return json.loads(encode_review(straight(), None, 3))


def decode(data: Any) -> DocumentDraft:
    return decode_review(json.dumps(data).encode(), NAMES).draft


def test_the_versions_are_spelled_out() -> None:
    assert FORMAT_VERSION == DESKEW_VERSION == 6
    assert DESPECKLE_VERSION == 5
    assert READ_VERSIONS == (1, 2, 3, 4, 5, 6)


def test_a_despeckle_only_draft_is_still_the_pinned_v5_file() -> None:
    assert encode_review(replace(plain(), despeckle=True), None, 3) == PINNED_V5
    assert encode_review(plain(), None, 3).startswith(MAIN_BYTES[:12])


def test_a_draft_without_an_angle_is_written_as_before() -> None:
    assert json.loads(encode_review(cropped(), None, 3))["version"] == 4
    assert json.loads(encode_review(on(cropped()), None, 3))["version"] == 5


@pytest.mark.parametrize("despeckle", [False, True])
def test_an_angle_is_written_as_version_6_with_the_version_5_shape(despeckle: bool) -> None:
    draft = replace(straight(), despeckle=despeckle)
    data = json.loads(encode_review(draft, None, 3))
    assert data["version"] == 6
    assert data["despeckle"] is despeckle
    assert data["cleanup"] == "off"
    assert data["edits"]["2"]["deskew"] == -27
    for edit in data["edits"].values():
        assert set(edit) == EDIT_KEYS_V6
    assert data["edits"]["1"]["deskew"] is None


@pytest.mark.parametrize("despeckle", [False, True])
def test_version_6_round_trips(despeckle: bool) -> None:
    draft = replace(set_document_cleanup(straight(), CleanupPolicy.LIGHT), despeckle=despeckle)
    stored = decode_review(encode_review(draft, None, 3), NAMES)
    assert stored.draft.edits == draft.edits
    assert stored.draft.edits[2].deskew_tenths == -27
    assert (stored.draft.despeckle, stored.draft.cleanup) == (despeckle, CleanupPolicy.LIGHT)


def test_version_6_keeps_a_crop_of_another_page() -> None:
    draft = set_deskew(cropped(), 1, 5)
    assert decode_review(encode_review(draft, None, 3), NAMES).draft.edits == draft.edits


def _edit(data: dict[str, Any], **changes: Any) -> dict[str, Any]:
    data["edits"]["2"].update(changes)
    return data


BAD_V6 = {
    "missing deskew": lambda d: (d["edits"]["2"].pop("deskew"), d)[1],
    "true": lambda d: _edit(d, deskew=True),
    "false": lambda d: _edit(d, deskew=False),
    "a float": lambda d: _edit(d, deskew=1.5),
    "a whole float": lambda d: _edit(d, deskew=2.0),
    "zero": lambda d: _edit(d, deskew=0),
    "too high": lambda d: _edit(d, deskew=101),
    "too low": lambda d: _edit(d, deskew=-101),
    "a string": lambda d: _edit(d, deskew="3"),
    "a list": lambda d: _edit(d, deskew=[3]),
    "an extra edit key": lambda d: _edit(d, extra=1),
    "missing despeckle": lambda d: (d.pop("despeckle"), d)[1],
    "despeckle one": lambda d: {**d, "despeckle": 1},
    "no top level cleanup": lambda d: (d.pop("cleanup"), d)[1],
    "a missing crop key": lambda d: (d["edits"]["2"].pop("crop"), d)[1],
}


@pytest.mark.parametrize("name", list(BAD_V6))
def test_version_6_refuses(name: str) -> None:
    with pytest.raises(ReviewFormatError):
        decode(BAD_V6[name](v6()))


def test_the_error_names_the_field_and_never_the_value() -> None:
    with pytest.raises(ReviewFormatError) as caught:
        decode(_edit(v6(), deskew=7777))
    assert "deskew" in str(caught.value)
    assert "7777" not in str(caught.value)


def test_version_6_accepts_the_limits_and_null() -> None:
    for value in (-100, -1, 1, 100, None):
        assert decode(_edit(v6(), deskew=value)).edits[2].deskew_tenths == value


def _older(version: int) -> dict[str, Any]:
    data = _old(version) if version < 5 else {**_old(4), "version": 5, "despeckle": False}
    if version == 5:
        data["cleanup"] = "off"
    return data


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_older_versions_never_hold_a_deskew_key(version: int) -> None:
    data = _older(version)
    data["edits"]["1"]["deskew"] = 5
    with pytest.raises(ReviewFormatError, match="deskew needs format version 6"):
        decode(data)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_older_files_still_read(version: int) -> None:
    assert all(edit.deskew_tenths is None for edit in decode(_older(version)).edits.values())
