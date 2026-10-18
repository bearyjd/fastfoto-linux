"""The thresholds of the ink-map flag are pinned: each one, moved, makes a test here fail
(checked by mutating a copy of ``inkmap.py``), and the box rule and the frame it works in."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.assess import assess_page
from fastfoto_linux.documents.draft import Flag
from fastfoto_linux.documents.inkmap import HIT_MIN, MARKS_MIN, hit_rates, ink_map
from tests.doc_synth_holes import sheet
from tests.documents import flags_helpers as fh
from tests.documents.flags_helpers import FAST_DPIS
from tests.documents.helpers import write_scene

NOTE = [fh.glyphs(40, 105, 4)]
OFF_MM = (2.5, 2.0)
BLEED = {Flag.SET_OFF, Flag.SHOW_THROUGH}


def settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), **changes)


def _analyse(tmp_path: Path, dpi: int, sheets: list[tuple[list, list]], **layout: Any):
    raw = tmp_path / "raw"
    raw.mkdir()
    paths = []
    for index, (front, back) in enumerate(sheets):
        extra = layout.get("frame_extra_mm", 0.0)
        gap = layout.get("gaps", [0.0] * len(sheets))[index]
        first, second = sheet(dpi, front, back, seed=index, frame_extra_mm=extra, gap_mm=gap)
        paths.append(write_scene(raw / f"page-{2 * index + 1:02d}.png", first))
        paths.append(write_scene(raw / f"page-{2 * index + 2:02d}.png", second))
    return analyse_document(paths, settings(tmp_path, duplex=True), encode=False)


def _rates(dpi: int, front: list, back: list) -> tuple[float, float]:
    first, second = fh.trimmed_pair(*sheet(dpi, front, back))
    marks = assess_page(second, None).marks
    return hit_rates(marks, ink_map(second), ink_map(first))


# ---- HIT_MIN ---------------------------------------------------------------------------------

FRONT_20 = [fh.glyphs(15, 70, 10), fh.glyphs(15, 80, 10)]


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_back_with_70_percent_on_print_is_not_flagged(tmp_path: Path, dpi: int) -> None:
    ghost = fh.ghost_of([fh.glyphs(15, 70, 10), fh.glyphs(15, 80, 4)], dpi, 60, shift_mm=OFF_MM)
    back = [ghost, fh.glyphs(50, 100, 6)]
    hit, control = _rates(dpi, FRONT_20, back)
    assert 0.6 <= hit < HIT_MIN
    assert control < 0.3
    draft = _analyse(tmp_path, dpi, [(fh.lines(), back), (FRONT_20, NOTE)])
    assert not draft.pages[1].flags & BLEED


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_back_with_95_percent_on_print_is_flagged(tmp_path: Path, dpi: int) -> None:
    ghost = fh.ghost_of([fh.glyphs(15, 70, 10), fh.glyphs(15, 80, 9)], dpi, 60, shift_mm=OFF_MM)
    back = [ghost, fh.glyphs(50, 100, 1)]
    hit, _ = _rates(dpi, FRONT_20, back)
    assert HIT_MIN <= hit < 0.99
    draft = _analyse(tmp_path, dpi, [(fh.lines(), back), (FRONT_20, NOTE)])
    assert Flag.SET_OFF in draft.pages[1].flags


# ---- MARKS_MIN -------------------------------------------------------------------------------

TWO = [fh.glyphs(15, 70, 2)]


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_two_marks_on_print_are_left_to_the_box_rule(tmp_path: Path, dpi: int) -> None:
    """Misregistered by more than a glyph, two marks do not overlap their boxes; the ink map is
    not asked for fewer than ``MARKS_MIN`` marks."""
    assert MARKS_MIN == 3
    ghost = fh.ghost_of(TWO, dpi, 60, shift_mm=OFF_MM)
    hit, _ = _rates(dpi, TWO, [ghost])
    assert hit == 1.0  # the ink map would match
    draft = _analyse(tmp_path, dpi, [(fh.lines(), [ghost]), (TWO, NOTE)])
    assert len(draft.pages[1].marks) == 2
    assert not draft.pages[1].flags & BLEED


# ---- REACH_MM --------------------------------------------------------------------------------


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_ghost_six_mm_off_is_not_flagged(tmp_path: Path, dpi: int) -> None:
    row = [fh.glyphs(15, 60, 12)]
    ghost = fh.ghost_of(row, dpi, 60, shift_mm=(0.0, 6.0))
    hit, _ = _rates(dpi, row, [ghost])
    assert hit < 0.5
    draft = _analyse(tmp_path, dpi, [(fh.lines(), [ghost]), (row, NOTE)])
    assert not draft.pages[1].flags & BLEED


# ---- the box rule: trim offsets, detail, and the frame placement -----------------------------


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_the_box_rule_works_in_the_frame_when_each_sheet_lies_differently(
    tmp_path: Path, dpi: int
) -> None:
    """The sheets lie 2 and 8 mm from the frame's left; the ghost is where the frame's mirror
    puts the next front's print. Equal placement of neighbouring sheets in the frame is assumed
    (a stack is fed the same way), so the boxes are compared in the frame, trim offsets added."""
    ghost = fh.frame_ghost_of(TWO, dpi, 60, frame_extra_mm=12.0, gap_mm=8.0, shift_mm=(0.3, 0.0))
    draft = _analyse(
        tmp_path,
        dpi,
        [(fh.lines(), [ghost]), (TWO, NOTE)],
        frame_extra_mm=12.0,
        gaps=[2.0, 8.0],
    )
    back = draft.pages[1]
    assert len(back.marks) == 2
    assert Flag.SET_OFF in back.flags
    assert back.detail == ("set_off_next",)
