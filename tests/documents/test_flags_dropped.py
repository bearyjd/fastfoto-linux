"""The flags of a page that is left out, and the neighbouring sheet's set-off."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.documents import assess as assess_module
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.assess import assess_page
from fastfoto_linux.documents.bleed import set_off
from fastfoto_linux.documents.draft import BoxN, Flag
from fastfoto_linux.documents.marks import find_marks
from tests.doc_synth_creases import with_creases
from tests.doc_synth_holes import STAPLES, holes_painter, sheet
from tests.documents import flags_helpers as fh
from tests.documents.blank_helpers import sheet as paper
from tests.documents.draft_helpers import LiveCounter  # noqa: F401
from tests.documents.flags_helpers import FAST_DPIS, assess_alone, assess_sides
from tests.documents.helpers import write_scene
from tests.documents.holes_helpers import mirrored, stapled_sheet

# ---- CREASE_IGNORED --------------------------------------------------------------------------


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_creased_blank_page_notes_the_crease(dpi: int) -> None:
    assessed = assess_alone(with_creases(paper(dpi), broken=True))
    assert assessed.verdict.blank
    assert assessed.flags == {Flag.CREASE_IGNORED}


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_clean_blank_page_has_no_flag(dpi: int) -> None:
    assessed = assess_alone(paper(dpi))
    assert assessed.verdict.blank
    assert assessed.flags == frozenset()
    assert assessed.marks == ()


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_crease_beside_writing_keeps_the_page_without_the_flag(dpi: int) -> None:
    scene = fh.glyphs(30, 50, 6)(with_creases(paper(dpi), broken=True))
    assessed = assess_alone(scene)
    assert not assessed.verdict.blank
    assert Flag.CREASE_IGNORED not in assessed.flags


def test_the_second_search_for_marks_is_made_on_blank_pages_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def spy(*args, **kwargs):
        calls.append(kwargs.get("ignore_faint_lines", False))
        return find_marks(*args, **kwargs)

    monkeypatch.setattr(assess_module, "find_marks", spy)
    assess_alone(fh.glyphs(30, 50, 6)(paper(200)))
    assert calls == [True]
    calls.clear()
    assess_alone(paper(200))
    assert calls == [True, False]


# ---- HOLES_MATCHED ---------------------------------------------------------------------------


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_staple_holes_seen_on_both_sides_are_noted(dpi: int) -> None:
    front, back = assess_sides(
        dpi, [holes_painter(STAPLES), *fh.lines()], [holes_painter(mirrored(STAPLES))]
    )
    assert back.verdict.blank
    assert back.flags == {Flag.HOLES_MATCHED}
    assert Flag.HOLES_MATCHED not in front.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_holes_with_nothing_opposite_do_not_say_matched(dpi: int) -> None:
    _, back = assess_sides(dpi, fh.lines(), [holes_painter(STAPLES)])
    assert not back.verdict.blank
    assert Flag.HOLES_MATCHED not in back.flags


def test_a_page_blank_for_its_holes_and_creases_has_both_flags() -> None:
    front, back = stapled_sheet(7)
    creased = with_creases(back, broken=True)
    first, second = fh.trimmed_pair(front, creased)
    assert assess_page(second, first).flags == {Flag.HOLES_MATCHED, Flag.CREASE_IGNORED}


# ---- SET_OFF: boxes only ---------------------------------------------------------------------

LEFT = BoxN(0.10, 0.20, 0.20, 0.25)
MIRROR_OF_LEFT = BoxN(0.80, 0.20, 0.90, 0.25)


def test_a_mirrored_neighbour_box_is_a_set_off() -> None:
    assert set_off([LEFT], [[MIRROR_OF_LEFT]])


def test_a_neighbour_box_that_is_not_mirrored_is_not() -> None:
    assert not set_off([LEFT], [[LEFT]])
    assert not set_off([LEFT], [[]])
    assert not set_off([LEFT], [])
    assert not set_off([], [[MIRROR_OF_LEFT]])


def test_the_overlap_must_reach_a_third_of_the_union() -> None:
    near = BoxN(0.77, 0.20, 0.87, 0.25)  # 0.07 of 0.13: 0.54
    far = BoxN(0.72, 0.20, 0.82, 0.25)  # 0.02 of 0.18: 0.11
    assert set_off([LEFT], [[near]])
    assert not set_off([LEFT], [[far]])


def test_most_of_the_marks_must_overlap() -> None:
    other = BoxN(0.40, 0.60, 0.45, 0.65)
    third = BoxN(0.40, 0.80, 0.45, 0.85)
    assert not set_off([LEFT, other, third], [[MIRROR_OF_LEFT]])
    assert set_off([LEFT, other], [[MIRROR_OF_LEFT]])


def test_the_previous_and_the_next_sheet_both_count() -> None:
    other = BoxN(0.40, 0.60, 0.45, 0.65)
    mirror_of_other = BoxN(0.55, 0.60, 0.60, 0.65)
    assert set_off([LEFT, other], [[MIRROR_OF_LEFT], [mirror_of_other]])
    assert set_off([LEFT], [[], [MIRROR_OF_LEFT]])


# ---- SET_OFF through a document --------------------------------------------------------------

PAGE_A = [fh.glyphs(15, 20, 8), fh.glyphs(15, 30, 8)]  # print of one sheet's front
PAGE_B = [fh.glyphs(15, 70, 6), fh.glyphs(15, 80, 6)]  # print of another sheet's front
PAGE_C = [fh.glyphs(45, 100, 3)]  # and of a third


def settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), **changes)


def _document(raw: Path, backs: list[list], dpi: int = 200) -> list[Path]:
    """A duplex stack of sheets: every front has print; ``backs`` are what each back shows."""
    fronts = [PAGE_A, PAGE_B, PAGE_C]
    paths: list[Path] = []
    for index, back in enumerate(backs):
        first, second = sheet(dpi, fronts[index], back, seed=index)
        paths.append(write_scene(raw / f"page-{2 * index + 1:02d}.png", first))
        paths.append(write_scene(raw / f"page-{2 * index + 2:02d}.png", second))
    return paths


def test_a_back_that_mirrors_the_next_sheets_print_is_set_off(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    pages = _document(raw, [[fh.ghost_of(PAGE_B, 200)], [fh.glyphs(40, 55, 5)]])
    draft = analyse_document(pages, settings(tmp_path, duplex=True))
    assert not draft.pages[1].blank
    assert Flag.SET_OFF in draft.pages[1].flags
    assert Flag.SET_OFF not in draft.pages[3].flags
    assert Flag.SET_OFF not in draft.pages[0].flags  # a front is never set off


def test_a_back_that_mirrors_the_previous_sheets_print_is_set_off(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    backs = [[fh.glyphs(40, 55, 5)], [fh.ghost_of(PAGE_A, 200)], [fh.glyphs(40, 55, 5)]]
    pages = _document(raw, backs)
    draft = analyse_document(pages, settings(tmp_path, duplex=True))
    assert Flag.SET_OFF in draft.pages[3].flags
    assert Flag.SET_OFF not in draft.pages[1].flags


def test_print_that_lies_elsewhere_is_not_a_set_off(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    pages = _document(raw, [[fh.ghost_of(PAGE_B, 200, upside_down=True)], [fh.glyphs(40, 55, 5)]])
    draft = analyse_document(pages, settings(tmp_path, duplex=True))
    assert Flag.SET_OFF not in draft.pages[1].flags


def test_without_duplex_nothing_is_set_off(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    pages = _document(raw, [[fh.ghost_of(PAGE_B, 200)], [fh.glyphs(40, 55, 5)]])
    draft = analyse_document(pages, settings(tmp_path, duplex=False))
    assert all(Flag.SET_OFF not in page.flags for page in draft.pages)
