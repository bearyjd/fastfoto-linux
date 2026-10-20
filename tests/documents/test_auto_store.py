"""Versioned Auto review sessions: strict v2 fields and safe v1 manual migration."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents.auto_colour import ColourDecision, ColourReason
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.draft_json import ReviewFormatError, decode_review, encode_review
from fastfoto_linux.documents.draft_store import REVIEW_FILE, open_draft, save_draft
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy
from tests.documents.auto_helpers import source_hashes, write_auto_pages
from tests.documents.draft_helpers import hand_draft
from tests.documents.edit_helpers import draft_of
from tests.documents.store_helpers import edited, store_settings


def auto_draft() -> DocumentDraft:
    draft = draft_of(2)
    decisions = (
        ColourDecision(ColourMode.COLOUR, ColourMode.BW, ColourReason.BILEVEL),
        ColourDecision(ColourMode.COLOUR, ColourMode.GREY, ColourReason.CONTINUOUS_TONE),
    )
    return replace(
        draft,
        pages=tuple(
            replace(page, colour=d) for page, d in zip(draft.pages, decisions, strict=True)
        ),
        edits={1: PageEdit(True, 1, ColourPolicy.COLOUR), 2: PageEdit(colour=ColourPolicy.AUTO)},
        order=(2, 1),
        splits=frozenset({1}),
        part_names={1: "Synthetic"},
    )


def test_v2_roundtrip_keeps_decisions_overrides_options_and_existing_edits(tmp_path: Path) -> None:
    draft = auto_draft()
    settings = store_settings(tmp_path, colour=ColourPolicy.AUTO)
    encoded = encode_review(draft, settings, 2)
    assert json.loads(encoded)["version"] == 2
    restored = decode_review(encoded, [page.name for page in draft.pages])
    assert restored.draft == draft
    assert restored.options is not None
    assert restored.options.colour == ColourPolicy.AUTO
    assert restored.analysis_version == 2


def test_v1_manual_session_reads_with_no_auto_or_page_override(tmp_path: Path) -> None:
    draft = draft_of(2)
    encoded = json.loads(encode_review(draft, store_settings(tmp_path, colour=ColourMode.GREY), 1))
    encoded["version"] = 1
    for page in encoded["pages"]:
        page.pop("colour", None)
    restored = decode_review(json.dumps(encoded).encode(), [page.name for page in draft.pages])
    assert restored.options is not None
    assert restored.options.colour == ColourMode.GREY
    assert all(page.colour is None for page in restored.draft.pages)
    assert all(edit.colour is None for edit in restored.draft.edits.values())


@pytest.mark.parametrize(
    ("field", "value"),
    [("mode", "auto"), ("source_kind", "palette"), ("reason", "unknown_reason")],
)
def test_v2_rejects_unknown_decision_values(field: str, value: str, tmp_path: Path) -> None:
    draft = auto_draft()
    data = json.loads(encode_review(draft, store_settings(tmp_path), 2))
    assert data["version"] == 2
    data["pages"][0]["colour"][field] = value
    with pytest.raises(ReviewFormatError):
        decode_review(json.dumps(data).encode(), [page.name for page in draft.pages])


def test_v2_rejects_invalid_override_and_future_format(tmp_path: Path) -> None:
    draft = auto_draft()
    data = json.loads(encode_review(draft, store_settings(tmp_path), 2))
    assert data["version"] == 2
    data["edits"]["1"]["colour"] = "invalid"
    with pytest.raises(ReviewFormatError):
        decode_review(json.dumps(data).encode(), [page.name for page in draft.pages])
    data["version"] = 99
    with pytest.raises(ReviewFormatError):
        decode_review(json.dumps(data).encode(), [page.name for page in draft.pages])


def test_v1_refresh_keeps_manual_policy_and_review_edits(tmp_path: Path) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("text", "blank", "stamp", "gradient"))
    original = source_hashes(pages)
    settings = store_settings(tmp_path, colour=ColourMode.GREY)
    draft = edited(hand_draft(pages, settings, blank={2}))
    save_draft(draft, settings)
    sidecar = pages[0].parent / REVIEW_FILE
    data = json.loads(sidecar.read_bytes())
    data["version"] = 1
    data["analysis_version"] = 1
    for page in data["pages"]:
        page.pop("colour", None)
    sidecar.write_text(json.dumps(data))
    restored = open_draft(pages[0].parent, pages, settings)
    assert all(page.colour is not None for page in restored.pages)
    assert (restored.edits, restored.order, restored.splits) == (
        draft.edits,
        draft.order,
        draft.splits,
    )
    assert settings.colour is ColourMode.GREY
    assert source_hashes(pages) == original
