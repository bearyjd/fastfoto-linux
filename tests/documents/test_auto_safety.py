"""Additional preservation and migration guards for the conservative Auto engine."""

import json
import threading
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.documents import analyse as analysis
from fastfoto_linux.documents import write as writer
from fastfoto_linux.documents.auto_colour import (
    ColourDecision,
    ColourReason,
    classify_colour,
    page_colour,
)
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_json import ReviewFormatError, decode_review, encode_review
from fastfoto_linux.documents.draft_store import REVIEW_FILE, open_draft, save_draft
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.errors import (
    DocumentCancelledError,
    DocumentError,
    DocumentSettingsError,
)
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy
from fastfoto_linux.documents.settings import check_settings
from tests.documents.auto_helpers import auto_page, pdf_modes, source_hashes, write_auto_pages
from tests.documents.draft_helpers import hand_draft
from tests.documents.edit_helpers import draft_of
from tests.documents.store_helpers import store_settings


def test_dark_shading_with_darker_text_is_not_flattened_to_solid_black() -> None:
    pixels = np.full((120, 100), 255, np.uint8)
    pixels[20:100, 15:85] = 70
    pixels[35:40, 25:75] = 0
    decision = classify_colour(LoadedPage(pixels, ColourMode.GREY, 100))
    assert decision.mode is ColourMode.GREY
    assert decision.reason is ColourReason.THRESHOLD_RISK


def test_a_tiny_ambiguous_colour_mark_abstains_from_reducing_colour() -> None:
    page = auto_page()
    page.pixels[40, 40] = (250, 243, 250)
    decision = classify_colour(page)
    assert decision.mode is ColourMode.COLOUR
    assert decision.reason is ColourReason.COLOUR_UNCERTAIN


def test_bilevel_safety_bounds_preserve_dense_dark_and_light_support() -> None:
    rng = np.random.default_rng(81)
    pixels = rng.choice(np.array([0, 24, 240, 255], np.uint8), size=(120, 100))
    page = LoadedPage(pixels, ColourMode.GREY, 100)
    pixels.setflags(write=False)
    assert classify_colour(page).mode is ColourMode.BW
    output = render_page(page, ColourMode.BW)
    assert np.array_equal(output, np.where(pixels >= 240, 255, 0))
    assert not np.shares_memory(output, pixels)


def test_readonly_source_can_be_classified_and_its_colour_preview_is_independent() -> None:
    page = auto_page("stamp")
    original = page.pixels.copy()
    page.pixels.setflags(write=False)
    assert classify_colour(page).mode is ColourMode.COLOUR
    output = render_page(page, ColourMode.COLOUR)
    output.fill(0)
    assert np.array_equal(page.pixels, original)


def test_v2_cannot_claim_an_output_richer_than_its_source(tmp_path: Path) -> None:
    draft = draft_of(1)
    data = json.loads(encode_review(draft, store_settings(tmp_path), 2))
    data["pages"][0]["colour"] = {
        "source_kind": "grey",
        "mode": "colour",
        "reason": "colour_marks",
    }
    with pytest.raises(ReviewFormatError):
        decode_review(json.dumps(data).encode(), [draft.pages[0].name])


def test_v1_cannot_silently_gain_an_auto_policy(tmp_path: Path) -> None:
    draft = draft_of(1)
    data = json.loads(encode_review(draft, store_settings(tmp_path), 1))
    data["version"] = 1
    data["options"]["colour"] = "auto"
    with pytest.raises(ReviewFormatError):
        decode_review(json.dumps(data).encode(), [draft.pages[0].name])


def test_a_missing_v2_decision_refreshes_analysis_and_preserves_colour_override(
    tmp_path: Path,
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp",))
    settings = store_settings(tmp_path, duplex=False)
    draft = replace(hand_draft(pages, settings), edits={1: PageEdit(colour=ColourPolicy.GREY)})
    save_draft(draft, settings)
    assert json.loads((pages[0].parent / REVIEW_FILE).read_bytes())["pages"][0]["colour"] is None
    restored = open_draft(pages[0].parent, pages, settings)
    assert restored.pages[0].colour is not None
    assert restored.edits[1].colour is ColourPolicy.GREY


def test_compatible_legacy_manual_cache_is_reused_without_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp",))
    settings = store_settings(tmp_path, duplex=False)
    draft = hand_draft(pages, settings)

    def refuse_decode(*args: object, **kwargs: object) -> LoadedPage:
        raise AssertionError("compatible manual cached bytes should not decode raw pixels")

    monkeypatch.setattr(writer, "load_page", refuse_decode)
    assert pdf_modes(writer.write_document(draft, settings).pdf) == ["/DeviceRGB"]


def test_cancellation_after_classification_never_publishes_or_changes_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp",))
    hashes = source_hashes(pages)
    cancel = threading.Event()

    def classify_and_cancel(page: LoadedPage) -> ColourDecision:
        decision = classify_colour(page)
        cancel.set()
        return decision

    monkeypatch.setattr(analysis, "classify_colour", classify_and_cancel)
    with pytest.raises(DocumentCancelledError):
        analysis.analyse_document(pages, store_settings(tmp_path), cancel=cancel)
    assert not list(tmp_path.glob("*.pdf"))
    assert source_hashes(pages) == hashes


def test_invalid_colour_policy_is_refused_by_settings_before_loading_pages(tmp_path: Path) -> None:
    with pytest.raises(DocumentSettingsError, match="colour mode"):
        check_settings(replace(store_settings(tmp_path), colour="sepia"))


def test_invalid_page_override_cannot_enter_an_immutable_edit() -> None:
    with pytest.raises(ValueError, match="colour"):
        PageEdit(colour="sepia")


def test_a_legacy_cached_reduction_cannot_silently_cap_an_explicit_richer_override(
    tmp_path: Path,
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp",))
    settings = store_settings(tmp_path, colour=ColourMode.BW, duplex=False)
    draft = replace(
        hand_draft(pages, settings), raw_dir=None, edits={1: PageEdit(colour=ColourPolicy.COLOUR)}
    )
    with pytest.raises(DocumentError, match="raw pages"):
        page_colour(draft, draft.pages[0], ColourPolicy.BW)
