"""Bleed-through that is not a clean shape match: dark marks on a back that lie where the NEXT
(or the previous, or the own) sheet's print lies, mirrored and a few mm off. A coarse ink map of
each page (about 20 dpi, bit-packed) is compared, with a control shifted 20 mm to tell dense
print from a real match. Verdicts do not change; only the flags."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft import Flag
from fastfoto_linux.documents.inkmap import ADVANTAGE_MIN, HIT_MIN, hit_rates, ink_map, lies_on
from tests.doc_synth_holes import sheet
from tests.documents import flags_helpers as fh
from tests.documents.flags_helpers import FAST_DPIS
from tests.documents.helpers import write_scene

PAGE_A = [fh.glyphs(15, 20, 8), fh.glyphs(15, 30, 8)]
PAGE_B = [fh.glyphs(15, 70, 6), fh.glyphs(15, 80, 6)]
TONES = [150, 60]  # a faint ghost and a dark one
OFF_MM = (2.5, 2.0)  # the ghost is not where the print is mirrored: misregistration
NOTE = [fh.glyphs(40, 95, 4)]
DENSE = [fh.glyphs(8, 12 + row * 8.0, 26) for row in range(12)]
LETTER_BYTES = 6 * 1024


def settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), **changes)


def _analyse(tmp_path: Path, dpi: int, sheets: list[tuple[list, list]]):
    raw = tmp_path / "raw"
    raw.mkdir()
    paths = []
    for index, (front, back) in enumerate(sheets):
        first, second = sheet(dpi, front, back, seed=index)
        paths.append(write_scene(raw / f"page-{2 * index + 1:02d}.png", first))
        paths.append(write_scene(raw / f"page-{2 * index + 2:02d}.png", second))
    return analyse_document(paths, settings(tmp_path, duplex=True), encode=False)


@pytest.mark.parametrize("tone", TONES)
@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_ghost_of_the_next_sheets_print_is_set_off_from_next(
    tmp_path: Path, dpi: int, tone: int
) -> None:
    ghost = fh.ghost_of(PAGE_B, dpi, tone, shift_mm=OFF_MM)
    draft = _analyse(tmp_path, dpi, [(PAGE_A, [ghost]), (PAGE_B, NOTE)])
    back = draft.pages[1]
    assert not back.blank
    assert Flag.SET_OFF in back.flags
    assert "set_off_next" in back.detail
    assert Flag.SET_OFF not in draft.pages[3].flags
    assert "set_off_next" in back.describe()


@pytest.mark.parametrize("tone", TONES)
@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_ghost_of_the_previous_sheets_print_is_set_off_from_prev(
    tmp_path: Path, dpi: int, tone: int
) -> None:
    ghost = fh.ghost_of(PAGE_A, dpi, tone, shift_mm=OFF_MM)
    draft = _analyse(tmp_path, dpi, [(PAGE_A, NOTE), (PAGE_B, [ghost])])
    assert Flag.SET_OFF in draft.pages[3].flags
    assert "set_off_prev" in draft.pages[3].detail
    assert Flag.SET_OFF not in draft.pages[1].flags


@pytest.mark.parametrize("tone", TONES)
@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_ghost_of_the_own_front_is_show_through(tmp_path: Path, dpi: int, tone: int) -> None:
    ghost = fh.ghost_of(PAGE_A, dpi, tone, shift_mm=OFF_MM)
    draft = _analyse(tmp_path, dpi, [(PAGE_A, [ghost]), (PAGE_B, NOTE)])
    assert Flag.SHOW_THROUGH in draft.pages[1].flags
    assert draft.pages[1].detail == ()


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_handwriting_unrelated_to_either_front_is_not_flagged(tmp_path: Path, dpi: int) -> None:
    note = [fh.glyphs(50, 95, 6), fh.glyphs(50, 105, 5)]
    draft = _analyse(tmp_path, dpi, [(PAGE_A, note), (PAGE_B, note)])
    for back in (draft.pages[1], draft.pages[3]):
        assert not back.blank
        assert not back.flags & {Flag.SET_OFF, Flag.SHOW_THROUGH}
        assert back.detail == ()


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_note_over_dense_print_is_flagged_as_a_hint_to_check(tmp_path: Path, dpi: int) -> None:
    """The accepted trade-off: a flag is a hint and never drops a page, so a note that lies on
    dense print (hit 1.0, control 0.75, advantage 0.25) is flagged "check", not missed."""
    note = [fh.glyphs(30, 46, 4)]
    draft = _analyse(tmp_path, dpi, [(DENSE, note), (DENSE, note)])
    for back in (draft.pages[1], draft.pages[3]):
        assert not back.blank
        assert back.flags & {Flag.SET_OFF, Flag.SHOW_THROUGH}


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_dense_print_hits_often_and_so_does_its_control(dpi: int) -> None:
    first, second = fh.trimmed_pair(*sheet(dpi, DENSE, [fh.glyphs(30, 46, 4)]))
    hit, control = hit_rates(_marks_of(second), ink_map(second), ink_map(first))
    assert hit >= HIT_MIN
    assert ADVANTAGE_MIN <= hit - control < 0.3


def test_a_control_of_85_percent_can_never_reach_the_advantage() -> None:
    """The documented false negative: on very dense pages the control is high, and a hit rate
    of at most 1.0 leaves less than ``ADVANTAGE_MIN``."""
    assert ADVANTAGE_MIN > 1.0 - 0.85


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_ghost_on_print_so_dense_that_the_control_is_high_is_not_flagged(dpi: int) -> None:
    first, _ = fh.trimmed_pair(*sheet(dpi, DENSE, []))
    ghost = fh.ghost_of(DENSE, dpi, 60, shift_mm=OFF_MM)
    _, back = fh.trimmed_pair(*sheet(dpi, [], [ghost]))
    marks = _marks_of(back)
    hit, control = hit_rates(marks, ink_map(back), ink_map(first))
    assert lies_on(marks, ink_map(back), ink_map(first)) is (
        hit >= HIT_MIN and hit - control >= ADVANTAGE_MIN
    )
    if control >= 0.85:
        assert not lies_on(marks, ink_map(back), ink_map(first))


def _marks_of(page):
    from fastfoto_linux.documents.assess import assess_page  # noqa: PLC0415

    return assess_page(page, None).marks


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_sparse_neighbour_is_not_a_match(tmp_path: Path, dpi: int) -> None:
    sparse = [fh.glyphs(15, 20, 1)]
    note = [fh.glyphs(40, 95, 4)]
    draft = _analyse(tmp_path, dpi, [(PAGE_A, note), (sparse, note)])
    assert not draft.pages[1].flags & {Flag.SET_OFF, Flag.SHOW_THROUGH}


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_the_hit_rate_of_a_ghost_is_high_and_its_control_low(dpi: int) -> None:
    front, _ = fh.trimmed_pair(*sheet(dpi, PAGE_B, []))
    ghost = fh.ghost_of(PAGE_B, dpi, 60, shift_mm=OFF_MM)
    _, back = fh.trimmed_pair(*sheet(dpi, [], [ghost]))
    marks = _marks_of(back)
    assert len(marks) >= 3
    hit, control = hit_rates(marks, ink_map(back), ink_map(front))
    assert hit >= HIT_MIN
    assert hit - control >= 0.3
    assert lies_on(marks, ink_map(back), ink_map(front))


def test_an_ink_map_is_a_few_kilobytes_and_keeps_no_pixels() -> None:
    page, _ = fh.trimmed_pair(
        *sheet(
            300,
            PAGE_A,
            [],
        )
    )
    ink = ink_map(page)
    assert len(ink.bits) <= LETTER_BYTES
    assert len(ink.bits) == -(-ink.cols * ink.rows // 8)
