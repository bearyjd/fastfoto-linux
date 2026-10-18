"""The verdict has one code path: ``blank_verdict``, which ``is_blank_beside`` and the flags use.
It must give the golden table's answers, and say what the answer was made of."""

import json
from pathlib import Path

import pytest

from fastfoto_linux.documents.assess import HOLE_REPORT_MAX_MARKS, assess_page, blank_verdict
from fastfoto_linux.documents.blank import is_blank_beside
from fastfoto_linux.documents.holes import all_are_holes, hole_report
from fastfoto_linux.documents.marks import find_marks
from tests.doc_synth_holes import STAPLES, holes_painter, sheet
from tests.documents import flags_helpers as fh
from tests.documents.golden_cases import verdict_table
from tests.documents.holes_helpers import mirrored, stapled_sheet, trimmed_sides

GOLDEN: dict[str, bool] = json.loads(
    (Path(__file__).parent / "golden_verdicts.json").read_text(encoding="utf-8")
)


def _blank(page, partner) -> bool:
    return blank_verdict(page, partner).blank


def test_blank_verdict_gives_the_golden_table_on_every_fixture() -> None:
    table = verdict_table(_blank)
    assert sorted(table) == sorted(GOLDEN)
    changed = sorted(label for label, verdict in table.items() if verdict != GOLDEN[label])
    assert changed == []


def test_the_assessment_carries_the_same_verdict() -> None:
    front, back = trimmed_sides(*stapled_sheet(1))
    assert assess_page(back, front).verdict == blank_verdict(back, front)
    assert assess_page(front, back).verdict == blank_verdict(front, back)


def test_is_blank_beside_is_the_verdict() -> None:
    front, back = trimmed_sides(*stapled_sheet(2))
    assert is_blank_beside(back, front) is blank_verdict(back, front).blank is True
    assert is_blank_beside(front, back) is blank_verdict(front, back).blank is False


def test_a_verdict_keeps_the_marks_it_judged() -> None:
    front, back = trimmed_sides(*stapled_sheet(3))
    verdict = blank_verdict(front, back)
    assert verdict.marks == find_marks(
        front.page, margin_mm=5.0, trimmed_bottom=front.tail_rows, ignore_faint_lines=True
    )
    assert len(verdict.marks) > HOLE_REPORT_MAX_MARKS
    assert verdict.holes is None  # print: the hole report is left out where it cannot matter
    stapled = blank_verdict(back, front)
    assert stapled.holes is not None
    assert stapled.holes.all_matched


def test_a_blank_page_has_no_marks_and_no_hole_report() -> None:
    page = fh.trimmed_pair(*sheet(200))[0]
    verdict = blank_verdict(page, None)
    assert (verdict.blank, verdict.marks, verdict.holes) == (True, (), None)


def test_without_a_partner_there_is_no_hole_report() -> None:
    page = fh.trimmed_pair(*sheet(200, [fh.glyphs(30, 50, 4)]))[0]
    verdict = blank_verdict(page, None)
    assert not verdict.blank
    assert verdict.holes is None


# ---- hole_report ---------------------------------------------------------------------------


def test_hole_report_of_a_stapled_back_counts_every_hole_as_matched() -> None:
    front, back = trimmed_sides(*stapled_sheet(4))
    marks = find_marks(back.page, margin_mm=5.0, trimmed_bottom=back.tail_rows)
    report = hole_report(marks, back, front)
    assert report.all_matched
    assert report.matched == report.candidates == len(marks) > 0


def test_hole_report_ignores_print_as_a_candidate() -> None:
    front, back = trimmed_sides(*stapled_sheet(5))
    marks = find_marks(front.page, margin_mm=5.0, trimmed_bottom=front.tail_rows)
    report = hole_report(marks, front, back)
    assert not report.all_matched
    assert 0 < report.matched == report.candidates < len(marks)


def test_hole_report_counts_a_hole_with_no_counterpart() -> None:
    first, second = sheet(200, [fh.glyphs(30, 50, 4)], [holes_painter(STAPLES)])
    front, back = fh.trimmed_pair(first, second)
    marks = find_marks(back.page, margin_mm=5.0, trimmed_bottom=back.tail_rows)
    report = hole_report(marks, back, front)
    assert (report.matched, report.all_matched) == (0, False)
    assert report.candidates > 0


@pytest.mark.parametrize("matching", [True, False])
def test_all_are_holes_is_the_reports_answer(matching: bool) -> None:
    back_holes = mirrored(STAPLES) if matching else [hole.moved(40.0, 30.0) for hole in STAPLES]
    first, second = sheet(200, [holes_painter(STAPLES)], [holes_painter(back_holes)])
    front, back = fh.trimmed_pair(first, second)
    marks = find_marks(back.page, margin_mm=5.0, trimmed_bottom=back.tail_rows)
    assert all_are_holes(marks, back, front) is hole_report(marks, back, front).all_matched
    assert all_are_holes(marks, back, front) is matching
