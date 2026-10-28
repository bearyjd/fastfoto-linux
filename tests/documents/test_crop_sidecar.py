"""Sidecar format 4: written only for a crop, read strictly, never granted to older files."""

import json
from dataclasses import replace
from typing import Any

import pytest

from fastfoto_linux.documents.analyse import ANALYSIS_VERSION
from fastfoto_linux.documents.crop_json import CropFormatError, parse_crop
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit, TrimBox
from fastfoto_linux.documents.draft_edit import set_crop, set_document_cleanup
from fastfoto_linux.documents.draft_json import (
    READ_VERSIONS,
    ReviewFormatError,
    StoredReview,
    decode_review,
    encode_review,
)
from fastfoto_linux.documents.draft_store import restore_edits
from fastfoto_linux.documents.modes import CleanupPolicy, ColourPolicy
from fastfoto_linux.documents.page_crop import PageCrop, crop_box
from fastfoto_linux.documents.sidecar_versions import CROP_VERSION
from tests.documents.edit_helpers import draft_of
from tests.documents.test_cleanup_sidecar import MAIN_BYTES, NAMES, plain

CROP = PageCrop(100, 200, 9000, 8000)


def cropped() -> DocumentDraft:
    return set_crop(plain(), 2, CROP)


def v4() -> dict[str, Any]:
    return json.loads(encode_review(set_document_cleanup(cropped(), CleanupPolicy.LIGHT), None, 3))


def decode(data: dict[str, Any]) -> DocumentDraft:
    return decode_review(json.dumps(data).encode(), NAMES).draft


def test_the_versions_are_spelled_out() -> None:
    assert CROP_VERSION == 4
    assert READ_VERSIONS == (1, 2, 3, 4, 5, 6)


def test_a_draft_without_a_crop_is_written_exactly_as_main_wrote_it() -> None:
    assert encode_review(plain(), None, ANALYSIS_VERSION) == MAIN_BYTES


def test_a_cleared_crop_leaves_no_trace() -> None:
    draft = set_crop(set_crop(plain(), 2, CROP), 2, None)
    assert encode_review(draft, None, ANALYSIS_VERSION) == MAIN_BYTES


def test_cleanup_without_a_crop_is_still_version_3_and_has_no_crop_key() -> None:
    data = encode_review(replace(plain(), cleanup=CleanupPolicy.LIGHT), None, 3)
    loaded = json.loads(data)
    assert loaded["version"] == 3
    assert b"crop" not in data


def test_a_crop_is_written_as_version_4_with_exactly_these_edit_keys() -> None:
    loaded = json.loads(encode_review(cropped(), None, 3))
    assert loaded["version"] == 4
    assert loaded["cleanup"] == "off"
    assert loaded["edits"]["2"] == {
        "include": None,
        "turns": 0,
        "colour": None,
        "cleanup": None,
        "crop": [100, 200, 9000, 8000],
    }
    for edit in loaded["edits"].values():
        assert set(edit) == {"include", "turns", "colour", "cleanup", "crop"}
    assert loaded["edits"]["1"]["crop"] is None


def test_version_4_round_trips() -> None:
    draft = set_document_cleanup(cropped(), CleanupPolicy.STRONG)
    stored = decode_review(encode_review(draft, None, 3), NAMES)
    assert stored.draft.edits == draft.edits
    assert stored.draft.edits[2].crop == CROP
    assert stored.draft.cleanup is CleanupPolicy.STRONG


def _edit(data: dict[str, Any], **changes: Any) -> dict[str, Any]:
    data["edits"]["2"].update(changes)
    return data


def _drop(data: dict[str, Any], key: str) -> dict[str, Any]:
    del data["edits"]["2"][key]
    return data


BAD_V4 = {
    "missing crop key": lambda d: _drop(d, "crop"),
    "extra key": lambda d: _edit(d, extra=1),
    "true": lambda d: _edit(d, crop=True),
    "a float": lambda d: _edit(d, crop=[1.5, 0, 9000, 9000]),
    "a float that is whole": lambda d: _edit(d, crop=[0.0, 0, 9000, 9000]),
    "a bool inside": lambda d: _edit(d, crop=[False, 0, 9000, 9000]),
    "three numbers": lambda d: _edit(d, crop=[0, 0, 9000]),
    "five numbers": lambda d: _edit(d, crop=[0, 0, 9000, 9000, 1]),
    "a string": lambda d: _edit(d, crop="0,0,1,1"),
    "too big": lambda d: _edit(d, crop=[0, 0, 10001, 9000]),
    "negative": lambda d: _edit(d, crop=[-1, 0, 9000, 9000]),
    "empty box": lambda d: _edit(d, crop=[5, 0, 5, 9000]),
    "upside down box": lambda d: _edit(d, crop=[0, 9, 9000, 3]),
    "no top level cleanup": lambda d: (d.pop("cleanup"), d)[1],
}


@pytest.mark.parametrize("name", list(BAD_V4))
def test_version_4_refuses(name: str) -> None:
    with pytest.raises(ReviewFormatError):
        decode(BAD_V4[name](v4()))


def test_version_4_accepts_a_null_crop_and_the_whole_page() -> None:
    assert decode(_edit(v4(), crop=None)).edits[2].crop is None
    assert decode(_edit(v4(), crop=[0, 0, 10000, 10000])).edits[2].crop == PageCrop(
        0, 0, 10000, 10000
    )


def _old(version: int) -> dict[str, Any]:
    data = json.loads(MAIN_BYTES)
    data["version"] = version
    if version == 3:
        data["cleanup"] = "off"
        for edit in data["edits"].values():
            edit["cleanup"] = None
    if version == 1:
        for edit in data["edits"].values():
            edit["colour"] = None
    return data


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("value", [None, [0, 0, 5000, 5000]])
def test_older_versions_refuse_a_crop_key(version: int, value: Any) -> None:
    data = _old(version)
    data["edits"]["1"]["crop"] = value
    with pytest.raises(ReviewFormatError, match="crop needs format version 4"):
        decode(data)


@pytest.mark.parametrize("version", [2, 3])
def test_older_versions_decode_with_no_crop(version: int) -> None:
    edits = decode(_old(version)).edits
    assert edits and all(edit.crop is None for edit in edits.values())


def test_a_crop_survives_a_new_analysis_with_a_different_trim_box() -> None:
    old = cropped()
    stored = StoredReview(old, ANALYSIS_VERSION, None)
    fresh = draft_of(3)
    smaller = replace(fresh.pages[1], trim=TrimBox(40, 30, 20, 10), dpi=100)
    new = replace(fresh, pages=(fresh.pages[0], smaller, fresh.pages[2]))
    restored = restore_edits(new, stored)
    crop = restored.edits[2].crop
    assert crop == CROP
    width, height = 600, 300  # the new trimmed page
    left, top, right, bottom = crop_box(width, height, smaller.dpi, crop)
    assert 0 <= left < right <= width and 0 <= top < bottom <= height
    assert right - left >= 20 and bottom - top >= 20  # 5 mm at 100 dpi is 20 px


def test_the_stored_colour_edits_are_kept_beside_a_crop() -> None:
    draft = set_crop(replace(draft_of(3), edits={1: PageEdit(True, 1, ColourPolicy.GREY)}), 1, CROP)
    assert decode_review(encode_review(draft, None, 3), NAMES[:3]).draft.edits == draft.edits


@pytest.mark.parametrize("value", [[0, 0, 9000, 9000, 1], [False, 0, 9000, 9000], [0, 0, 9000]])
def test_parse_crop_refuses_these_by_itself(value: list) -> None:
    with pytest.raises(CropFormatError):
        parse_crop(value, "a crop")
