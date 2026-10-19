"""A faint component near dark text must survive even inside the antialias radius."""

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents.auto_colour import ColourDecision, ColourReason, classify_colour
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_json import encode_review
from fastfoto_linux.documents.draft_store import REVIEW_FILE, open_draft
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy
from fastfoto_linux.documents.units import mm_to_px
from tests.documents.draft_helpers import hand_draft
from tests.documents.store_helpers import store_settings


@pytest.mark.parametrize("dpi", [100, 300, 600])
@pytest.mark.parametrize("kind", [ColourMode.GREY, ColourMode.COLOUR])
def test_detached_faint_line_across_a_white_gap_is_preserved(dpi: int, kind: ColourMode) -> None:
    grey = np.full((dpi, dpi), 255, np.uint8)
    x = dpi // 2
    rows = slice(dpi // 4, 3 * dpi // 4)
    grey[rows, x : x + max(1, dpi // 100)] = 0
    gap = max(1, round(dpi / 254))
    grey[rows, x - 2 * gap : x - gap] = 230
    faint = grey == 230
    pixels = np.repeat(grey[:, :, None], 3, axis=2) if kind is ColourMode.COLOUR else grey
    original = pixels.copy()
    page = LoadedPage(pixels, kind, dpi)
    decision = classify_colour(page)
    rendered = render_page(page, decision.mode)
    assert (rendered[faint] == 230).all(), "Auto must retain every detached faint-stroke pixel"
    assert decision.mode is ColourMode.GREY
    assert decision.reason is ColourReason.FAINT_MARKS
    assert np.array_equal(pixels, original)


@pytest.mark.parametrize("dpi", [300, 600])
def test_detached_shading_inside_the_edge_radius_retains_its_tones(dpi: int) -> None:
    grey = np.full((dpi, dpi), 255, np.uint8)
    x = dpi // 2
    rows = slice(dpi // 4, 3 * dpi // 4)
    grey[rows, x : x + max(1, dpi // 100)] = 0
    gap = max(1, round(dpi / 254))
    top, bottom = dpi // 2, dpi // 2 + dpi // 50
    grey[top:bottom, x - 2 * gap : x - gap] = 170
    grey[top:bottom:2, x - 2 * gap : x - gap] = 200
    shading = (grey == 170) | (grey == 200)
    page = LoadedPage(grey, ColourMode.GREY, dpi)
    decision = classify_colour(page)
    rendered = render_page(page, decision.mode)
    assert np.array_equal(rendered[shading], grey[shading])
    assert decision.mode is ColourMode.GREY


@pytest.mark.parametrize("dpi", [300, 600])
def test_connected_diagonal_antialias_edges_still_allow_bilevel(dpi: int) -> None:
    grey = np.full((mm_to_px(45, dpi), mm_to_px(55, dpi)), 245, np.uint8)
    start = (mm_to_px(10, dpi), mm_to_px(10, dpi))
    end = (mm_to_px(45, dpi), mm_to_px(35, dpi))
    cv2.line(grey, start, end, 45, mm_to_px(0.25, dpi), cv2.LINE_AA)
    page = LoadedPage(grey, ColourMode.GREY, dpi)
    decision = classify_colour(page)
    assert decision.mode is ColourMode.BW
    assert (render_page(page, decision.mode)[grey < 96] == 0).all()


def test_cached_pre_fix_bilevel_decision_is_refreshed_and_edits_retained(tmp_path: Path) -> None:
    dpi = 300
    grey = np.full((dpi, dpi), 255, np.uint8)
    grey[75:225, 150:153] = 0
    grey[75:225, 148:149] = 230
    folder = tmp_path / "pages"
    folder.mkdir()
    path = folder / "page-0001.png"
    Image.fromarray(grey).save(path, dpi=(dpi, dpi))
    original = path.read_bytes()
    settings = store_settings(tmp_path, duplex=False, colour=ColourPolicy.AUTO)
    draft = hand_draft((path,), replace(settings, colour=ColourMode.GREY))
    wrong = ColourDecision(ColourMode.GREY, ColourMode.BW, ColourReason.BILEVEL)
    draft = replace(
        draft,
        pages=(replace(draft.pages[0], colour=wrong),),
        edits={1: PageEdit(True, 1, ColourPolicy.AUTO)},
    )
    (folder / REVIEW_FILE).write_bytes(encode_review(draft, settings, 2))
    restored = open_draft(folder, (path,), settings)
    assert restored.pages[0].colour is not None
    assert restored.pages[0].colour.mode is ColourMode.GREY
    assert restored.edits == draft.edits
    assert path.read_bytes() == original
