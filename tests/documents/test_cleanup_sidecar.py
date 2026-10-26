"""Sidecar format 3: written only when cleanup is set, read strictly, never granted to old files."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents.analyse import ANALYSIS_VERSION
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.draft_json import (
    CROP_VERSION,
    ReviewFormatError,
    decode_review,
    encode_review,
)
from fastfoto_linux.documents.draft_store import (
    StoredReview,
    open_draft,
    read_review,
    restore_edits,
    save_draft,
)
from fastfoto_linux.documents.modes import CleanupPolicy, ColourPolicy
from tests.documents.edit_helpers import draft_of
from tests.documents.store_helpers import put_sidecar, raw_folder, store_settings, touch_page

# What the encoder of main (format version 2) wrote for ``plain()``.
MAIN_BYTES = (
    b'{"version":2,"analysis_version":3,"duplex":false,"keep_blank":false,"pages":[{"name":"page-01'
    b'.png","size":1,"mtime_ns":1,"dpi":100,"trim":[0,0,0,0],"band_bottom":false,"blank":false,"par'
    b'tner":null,"flags":[],"marks":[],"detail":[],"colour":null},{"name":"page-02.png","size":1,"m'
    b'time_ns":1,"dpi":100,"trim":[0,0,0,0],"band_bottom":false,"blank":false,"partner":null,"flags'
    b'":[],"marks":[],"detail":[],"colour":null},{"name":"page-03.png","size":1,"mtime_ns":1,"dpi":'
    b'100,"trim":[0,0,0,0],"band_bottom":false,"blank":false,"partner":null,"flags":[],"marks":[],"'
    b'detail":[],"colour":null}],"edits":{"1":{"include":true,"turns":1,"colour":"grey"},"3":{"incl'
    b'ude":null,"turns":2,"colour":null}},"order":[2,1,3],"splits":[2],"part_names":{"1":"Syntheti'
    b'c"}}'
)
NAMES = [f"page-{n:02d}.png" for n in (1, 2, 3)]


def plain() -> DocumentDraft:
    return replace(
        draft_of(3),
        edits={1: PageEdit(True, 1, ColourPolicy.GREY), 3: PageEdit(None, 2, None)},
        order=(2, 1, 3),
        splits=frozenset({2}),
        part_names={1: "Synthetic"},
    )


def with_cleanup() -> DocumentDraft:
    draft = plain()
    return replace(
        draft,
        cleanup=CleanupPolicy.STRONG,
        edits={
            **draft.edits,
            2: PageEdit(cleanup=CleanupPolicy.OFF),
            3: PageEdit(None, 2, None, CleanupPolicy.LIGHT),
        },
    )


def v3() -> dict[str, Any]:
    return json.loads(encode_review(with_cleanup(), None, ANALYSIS_VERSION))


def decode(data: Any) -> StoredReview:
    return decode_review(json.dumps(data).encode(), NAMES)


def test_a_draft_without_cleanup_is_written_as_main_wrote_it() -> None:
    assert encode_review(plain(), None, ANALYSIS_VERSION) == MAIN_BYTES


def test_the_analysis_version_stays_3() -> None:
    assert ANALYSIS_VERSION == 3
    assert CROP_VERSION == 4  # the crop made it 4; cleanup alone is still written as 3


def test_the_document_level_alone_makes_version_3() -> None:
    data = json.loads(encode_review(replace(plain(), cleanup=CleanupPolicy.LIGHT), None, 3))
    assert data["version"] == 3 and data["cleanup"] == "light"


def test_one_page_override_alone_makes_version_3() -> None:
    draft = replace(plain(), edits={2: PageEdit(cleanup=CleanupPolicy.STRONG)})
    data = json.loads(encode_review(draft, None, 3))
    assert data["version"] == 3 and data["cleanup"] == "off"
    assert data["edits"] == {
        "2": {"include": None, "turns": 0, "colour": None, "cleanup": "strong"}
    }


def test_version_3_gives_every_edit_exactly_four_keys() -> None:
    for edit in v3()["edits"].values():
        assert set(edit) == {"include", "turns", "colour", "cleanup"}
    assert v3()["edits"]["1"]["cleanup"] is None


def test_version_3_roundtrips_exactly() -> None:
    draft = with_cleanup()
    stored = decode_review(encode_review(draft, None, ANALYSIS_VERSION), NAMES)
    assert stored.draft == draft
    assert stored.draft.cleanup is CleanupPolicy.STRONG
    assert stored.draft.edits[3].cleanup is CleanupPolicy.LIGHT
    assert stored.draft.edits[2].cleanup is CleanupPolicy.OFF


def test_version_2_decodes_with_cleanup_off() -> None:
    stored = decode_review(MAIN_BYTES, NAMES)
    assert stored.draft.cleanup is CleanupPolicy.OFF
    assert all(edit.cleanup is None for edit in stored.draft.edits.values())


def test_version_1_decodes_with_cleanup_off() -> None:
    data = json.loads(MAIN_BYTES)
    data["version"] = 1
    data["edits"]["1"]["colour"] = None
    stored = decode(data)
    assert stored.draft.cleanup is CleanupPolicy.OFF
    assert all(edit.cleanup is None for edit in stored.draft.edits.values())


@pytest.mark.parametrize("bad", ["medium", "", "LIGHT", True, 1, None, ["off"], {"a": 1}])
def test_a_bad_document_cleanup_is_refused(bad: Any) -> None:
    data = v3()
    data["cleanup"] = bad
    with pytest.raises(ReviewFormatError):
        decode(data)


def test_a_missing_document_cleanup_is_refused_in_version_3() -> None:
    data = v3()
    del data["cleanup"]
    with pytest.raises(ReviewFormatError):
        decode(data)


@pytest.mark.parametrize("bad", ["medium", "", "Strong", True, 0, ["off"]])
def test_a_bad_edit_cleanup_is_refused(bad: Any) -> None:
    data = v3()
    data["edits"]["3"]["cleanup"] = bad
    with pytest.raises(ReviewFormatError):
        decode(data)


@pytest.mark.parametrize("key", ["include", "turns", "colour", "cleanup"])
def test_a_missing_edit_key_is_refused_in_version_3(key: str) -> None:
    data = v3()
    del data["edits"]["1"][key]
    with pytest.raises(ReviewFormatError):
        decode(data)


def test_an_extra_edit_key_is_refused_in_version_3() -> None:
    data = v3()
    data["edits"]["1"]["sharpen"] = 1
    with pytest.raises(ReviewFormatError):
        decode(data)


@pytest.mark.parametrize("version", [1, 2])
def test_cleanup_in_an_old_version_is_refused(version: int) -> None:
    data = json.loads(MAIN_BYTES)
    data["version"] = version
    data["edits"]["1"]["colour"] = None
    data["cleanup"] = "strong"
    with pytest.raises(ReviewFormatError, match="cleanup needs format version 3"):
        decode(data)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("value", [None, "light", "off"])
def test_a_page_cleanup_in_an_old_version_is_refused(version: int, value: Any) -> None:
    data = json.loads(MAIN_BYTES)
    data["version"] = version
    data["edits"]["1"]["colour"] = None
    data["edits"]["3"]["cleanup"] = value
    with pytest.raises(ReviewFormatError, match="cleanup needs format version 3"):
        decode(data)


@pytest.mark.parametrize("version", [0, 4, "3", 3.0, True, None])
def test_other_versions_are_refused(version: Any) -> None:
    for shape in (v3(), json.loads(MAIN_BYTES)):  # whatever else the file holds
        with pytest.raises(ReviewFormatError):
            decode({**shape, "version": version})


# --- the store ---------------------------------------------------------------------------------


def old_sidecar(tmp_path: Path) -> tuple[Path, tuple[Path, ...]]:
    """A raw folder whose sidecar is a version 2 file, saved by main."""
    folder, pages = raw_folder(tmp_path)
    settings = store_settings(tmp_path)
    draft = open_draft(folder, pages, settings, fresh=True)
    save_draft(draft, settings)
    return folder, pages


def test_a_version_2_sidecar_opens_with_cleanup_off_when_fresh(tmp_path: Path) -> None:
    folder, pages = old_sidecar(tmp_path)
    draft = open_draft(folder, pages, store_settings(tmp_path, cleanup=CleanupPolicy.STRONG))
    assert draft.cleanup is CleanupPolicy.OFF


def test_a_version_2_sidecar_opens_with_cleanup_off_when_stale(tmp_path: Path) -> None:
    folder, pages = old_sidecar(tmp_path)
    touch_page(pages[0])
    draft = open_draft(folder, pages, store_settings(tmp_path, cleanup=CleanupPolicy.STRONG))
    assert draft.cleanup is CleanupPolicy.OFF


def test_a_version_3_sidecar_keeps_its_cleanup_fresh_or_stale(tmp_path: Path) -> None:
    folder, pages = raw_folder(tmp_path)
    settings = store_settings(tmp_path, cleanup=CleanupPolicy.OFF)
    draft = replace(open_draft(folder, pages, settings, fresh=True), cleanup=CleanupPolicy.LIGHT)
    save_draft(draft, settings)
    assert open_draft(folder, pages, settings).cleanup is CleanupPolicy.LIGHT
    touch_page(pages[1])
    assert open_draft(folder, pages, settings).cleanup is CleanupPolicy.LIGHT


def test_a_new_analysis_is_seeded_from_the_settings(tmp_path: Path) -> None:
    folder, pages = raw_folder(tmp_path)
    draft = open_draft(
        folder, pages, store_settings(tmp_path, cleanup=CleanupPolicy.LIGHT), fresh=True
    )
    assert draft.cleanup is CleanupPolicy.LIGHT


def test_restore_edits_copies_the_cleanup_level_and_the_page_overrides() -> None:
    saved = with_cleanup()
    stored = StoredReview(saved, ANALYSIS_VERSION, None)
    fresh = replace(draft_of(3), cleanup=CleanupPolicy.LIGHT)
    restored = restore_edits(fresh, stored)
    assert restored.cleanup is CleanupPolicy.STRONG
    assert restored.edits[3].cleanup is CleanupPolicy.LIGHT
    off = restore_edits(
        replace(fresh, cleanup=CleanupPolicy.STRONG), StoredReview(plain(), 3, None)
    )
    assert off.cleanup is CleanupPolicy.OFF


def test_a_version_3_file_cannot_pose_as_version_2(tmp_path: Path) -> None:
    folder, pages = raw_folder(tmp_path)
    settings = store_settings(tmp_path)
    draft = replace(open_draft(folder, pages, settings, fresh=True), cleanup=CleanupPolicy.STRONG)
    save_draft(draft, settings)
    put_back = json.loads((folder / "review.json").read_text(encoding="utf-8"))
    assert put_back["version"] == 3 and put_back["cleanup"] == "strong"
    put_sidecar(folder, {**put_back, "version": 2})
    assert read_review(folder, pages) is None
