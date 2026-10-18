"""``analyse_document`` puts the flags and the mark boxes of each page in the draft, and nothing
about the verdicts changes."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft import Flag, sorted_flags
from tests.doc_synth_holes import STAPLES, holes_painter, sheet
from tests.documents import flags_helpers as fh
from tests.documents.helpers import write_scene
from tests.documents.holes_helpers import mirrored

MAX_BOXES = 24


def settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), **changes)


def _stack(raw: Path, sheets: list[tuple[Any, Any]]) -> list[Path]:
    raw.mkdir()
    paths = []
    for number, scene in enumerate([side for pair in sheets for side in pair], start=1):
        paths.append(write_scene(raw / f"page-{number:02d}.png", scene))
    return paths


def _two_sheets() -> list[tuple[Any, Any]]:
    stapled = sheet(200, [holes_painter(STAPLES), *fh.lines()], [holes_painter(mirrored(STAPLES))])
    signed = sheet(200, fh.lines(), [fh.glyphs(40, 55, 2)], seed=3)
    return [stapled, signed]


def test_each_page_carries_its_flags_and_boxes(tmp_path: Path) -> None:
    pages = _stack(tmp_path / "raw", _two_sheets())
    draft = analyse_document(pages, settings(tmp_path, duplex=True), encode=False)
    assert [page.blank for page in draft.pages] == [False, True, False, False]
    assert draft.pages[1].flags == {Flag.HOLES_MATCHED}
    assert draft.pages[1].partner == 1
    assert Flag.FEW_MARKS in draft.pages[3].flags
    assert draft.pages[0].flags == frozenset()


def test_boxes_are_shares_of_the_trimmed_page(tmp_path: Path) -> None:
    pages = _stack(tmp_path / "raw", _two_sheets())
    draft = analyse_document(pages, settings(tmp_path, duplex=True), encode=False)
    for page in draft.pages:
        assert len(page.marks) <= MAX_BOXES
        for box in page.marks:
            assert 0.0 <= box.x0 < box.x1 <= 1.0
            assert 0.0 <= box.y0 < box.y1 <= 1.0
    assert draft.pages[1].marks == ()  # a page of holes is blank: its holes are not drawn
    assert len(draft.pages[3].marks) == 2
    assert all(box.x0 > 0.3 for box in draft.pages[3].marks)  # the signature, a third in


def test_a_page_with_many_marks_keeps_the_biggest_boxes_only(tmp_path: Path) -> None:
    crowded = [fh.glyphs(15, 12 + row * 6.0, 14) for row in range(10)]
    pages = _stack(tmp_path / "raw", [sheet(200, crowded, [])])
    draft = analyse_document(pages, settings(tmp_path, duplex=True), encode=False)
    assert len(draft.pages[0].marks) == MAX_BOXES


def test_a_page_that_stays_by_default_is_not_judged_with_keep_blank(tmp_path: Path) -> None:
    pages = _stack(tmp_path / "raw", _two_sheets())
    draft = analyse_document(pages, settings(tmp_path, duplex=True, keep_blank=True), encode=False)
    assert [page.flags for page in draft.pages] == [frozenset()] * 4
    assert [page.marks for page in draft.pages] == [()] * 4


def test_the_flags_do_not_change_what_is_dropped(tmp_path: Path) -> None:
    pages = _stack(tmp_path / "raw", _two_sheets())
    draft = analyse_document(pages, settings(tmp_path, duplex=True))
    assert draft.dropped == (2,)
    assert [page.encoded is not None for page in draft.pages] == [True, False, True, True]


def test_describe_prints_numbers_and_flags_in_a_stable_order(tmp_path: Path) -> None:
    pages = _stack(tmp_path / "raw", _two_sheets())
    draft = analyse_document(pages, settings(tmp_path, duplex=True), encode=False)
    assert draft.pages[1].describe() == "page 2 blank flags=holes_matched marks=0"
    assert draft.pages[0].describe() == "page 1 kept flags=- marks=" + str(
        len(draft.pages[0].marks)
    )
    assert sorted_flags({Flag.SET_OFF, Flag.EDGE_ONLY, Flag.FEW_MARKS}) == (
        Flag.EDGE_ONLY,
        Flag.FEW_MARKS,
        Flag.SET_OFF,
    )


def test_the_second_search_for_marks_runs_on_blank_pages_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastfoto_linux.documents import assess as assess_module  # noqa: PLC0415

    calls: list[bool] = []
    real = assess_module.find_marks

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs.get("ignore_faint_lines", False))
        return real(*args, **kwargs)

    monkeypatch.setattr(assess_module, "find_marks", spy)
    pages = _stack(tmp_path / "raw", _two_sheets())
    analyse_document(pages, settings(tmp_path, duplex=True), encode=False)
    assert calls.count(True) == 4  # every page is judged once
    assert calls.count(False) == 1  # the blank one only
