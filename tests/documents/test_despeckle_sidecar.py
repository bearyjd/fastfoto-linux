"""Sidecar format 5: written only for despeckle, read strictly, never granted to older files."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents.analyse import ANALYSIS_VERSION
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_edit import set_crop, set_document_cleanup
from fastfoto_linux.documents.draft_json import (
    READ_VERSIONS,
    ReviewFormatError,
    StoredReview,
    decode_review,
    encode_review,
)
from fastfoto_linux.documents.draft_store import open_draft, read_review, restore_edits, save_draft
from fastfoto_linux.documents.modes import CleanupPolicy
from fastfoto_linux.documents.sidecar_versions import CROP_VERSION, DESPECKLE_VERSION
from tests.documents.store_helpers import (
    analysed,
    put_sidecar,
    raw_folder,
    store_settings,
    touch_page,
)
from tests.documents.test_cleanup_sidecar import MAIN_BYTES, NAMES, plain
from tests.documents.test_crop_sidecar import CROP, cropped


def on(draft: DocumentDraft) -> DocumentDraft:
    return replace(draft, despeckle=True)


def v5() -> dict[str, Any]:
    return json.loads(
        encode_review(on(set_document_cleanup(cropped(), CleanupPolicy.LIGHT)), None, 3)
    )


def decode(data: Any) -> DocumentDraft:
    return decode_review(json.dumps(data).encode(), NAMES).draft


def test_the_versions_are_spelled_out() -> None:
    assert DESPECKLE_VERSION == 5
    assert CROP_VERSION == 4
    assert READ_VERSIONS == (1, 2, 3, 4, 5, 6)


def test_a_draft_without_despeckle_is_written_as_main_wrote_it() -> None:
    assert encode_review(plain(), None, ANALYSIS_VERSION) == MAIN_BYTES


def test_a_cropped_draft_still_writes_version_4() -> None:
    assert json.loads(encode_review(cropped(), None, 3))["version"] == 4


def test_cleanup_alone_still_writes_version_3() -> None:
    data = json.loads(encode_review(replace(plain(), cleanup=CleanupPolicy.LIGHT), None, 3))
    assert data["version"] == 3
    assert "despeckle" not in data


@pytest.mark.parametrize("make", [plain, cropped])
def test_despeckle_is_written_as_version_5_with_the_version_4_shape(make) -> None:
    data = json.loads(encode_review(on(make()), None, 3))
    assert data["version"] == 5
    assert data["despeckle"] is True
    assert data["cleanup"] == "off"
    for edit in data["edits"].values():
        assert set(edit) == {"include", "turns", "colour", "cleanup", "crop"}


@pytest.mark.parametrize("make", [plain, cropped])
@pytest.mark.parametrize("level", [CleanupPolicy.OFF, CleanupPolicy.STRONG])
def test_version_5_round_trips(make, level: CleanupPolicy) -> None:
    draft = on(set_document_cleanup(make(), level))
    stored = decode_review(encode_review(draft, None, 3), NAMES)
    assert stored.draft.despeckle is True
    assert stored.draft.edits == draft.edits
    assert stored.draft.cleanup is level


def test_version_5_keeps_a_crop() -> None:
    assert decode(v5()).edits[2].crop == CROP


def _edit(data: dict[str, Any], **changes: Any) -> dict[str, Any]:
    data["edits"]["2"].update(changes)
    return data


BAD_V5 = {
    "missing despeckle": lambda d: (d.pop("despeckle"), d)[1],
    "one": lambda d: {**d, "despeckle": 1},
    "a string": lambda d: {**d, "despeckle": "true"},
    "null": lambda d: {**d, "despeckle": None},
    "no top level cleanup": lambda d: (d.pop("cleanup"), d)[1],
    "an extra edit key": lambda d: _edit(d, extra=1),
    "a missing crop key": lambda d: (d["edits"]["2"].pop("crop"), d)[1],
}


@pytest.mark.parametrize("name", list(BAD_V5))
def test_version_5_refuses(name: str) -> None:
    with pytest.raises(ReviewFormatError):
        decode(BAD_V5[name](v5()))


def test_version_5_accepts_false() -> None:
    stored = decode_review(json.dumps({**v5(), "despeckle": False}).encode(), NAMES)
    assert stored.draft.despeckle is False


def _old(version: int) -> dict[str, Any]:
    data = json.loads(MAIN_BYTES)
    data["version"] = version
    if version >= 3:
        data["cleanup"] = "off"
        for edit in data["edits"].values():
            edit["cleanup"] = None
    if version >= 4:
        for edit in data["edits"].values():
            edit["crop"] = None
    if version == 1:
        for edit in data["edits"].values():
            edit["colour"] = None
    return data


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("value", [True, False])
def test_older_versions_never_hold_despeckle(version: int, value: bool) -> None:
    with pytest.raises(ReviewFormatError, match="despeckle needs format version 5"):
        decode({**_old(version), "despeckle": value})


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_older_versions_read_as_off(version: int) -> None:
    stored = decode_review(json.dumps(_old(version)).encode(), NAMES)
    assert stored.draft.despeckle is False


def test_restore_edits_copies_despeckle_from_a_version_5_sidecar() -> None:
    stored = StoredReview(on(plain()), ANALYSIS_VERSION, None)
    assert restore_edits(replace(plain(), despeckle=False), stored).despeckle is True
    off = StoredReview(plain(), ANALYSIS_VERSION, None)
    assert restore_edits(replace(plain(), despeckle=True), off).despeckle is False


def test_a_version_4_sidecar_never_takes_despeckle_from_the_settings(tmp_path: Path) -> None:
    folder, pages = raw_folder(tmp_path)
    settings = store_settings(tmp_path / "out", duplex=False)
    (tmp_path / "out").mkdir()
    save_draft(set_crop(analysed(folder, pages, settings), 1, CROP), settings)
    assert json.loads((folder / "review.json").read_text())["version"] == 4
    wants = replace(settings, despeckle=True)
    assert open_draft(folder, pages, wants).despeckle is False  # fresh
    touch_page(pages[0])
    assert open_draft(folder, pages, wants).despeckle is False  # stale
    assert open_draft(folder, pages, wants, fresh=True).despeckle is True  # no sidecar used


def test_a_version_5_sidecar_is_kept_fresh_and_stale(tmp_path: Path) -> None:
    folder, pages = raw_folder(tmp_path)
    (tmp_path / "out").mkdir()
    settings = store_settings(tmp_path / "out", duplex=False)
    save_draft(on(analysed(folder, pages, settings)), settings)
    assert read_review(folder, pages).draft.despeckle is True  # type: ignore[union-attr]
    assert open_draft(folder, pages, settings).despeckle is True
    touch_page(pages[0])
    assert open_draft(folder, pages, settings).despeckle is True


def test_a_hand_written_version_5_file_is_read(tmp_path: Path) -> None:
    folder, pages = raw_folder(tmp_path)
    (tmp_path / "out").mkdir()
    settings = store_settings(tmp_path / "out", duplex=False)
    save_draft(on(analysed(folder, pages, settings)), settings)
    data = json.loads((folder / "review.json").read_text())
    put_sidecar(folder, {**data, "despeckle": 1})
    assert read_review(folder, pages) is None  # refused whole
