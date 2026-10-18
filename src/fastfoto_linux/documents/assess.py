"""One verdict code path for a page, and the flags that explain it.

``blank_verdict`` is the only place that decides whether a page is blank (``blank.is_blank_beside``
returns its ``blank``). ``assess_page`` wraps it and adds the flags a reviewer reads: a flag only
explains, it never drops or keeps a page. A page that stays can have

* ``FEW_MARKS``: at most ``FEW_MARKS_MAX`` marks, and their boxes together under ``FEW_MARKS_MM2``
  (2 cm2): a signature, a stray mark;
* ``EDGE_ONLY``: every mark lies within ``holes.EDGE_ZONE_MM`` of an edge of the page;
* ``HOLE_LIKE``: a mark has a hole's size, shape, grey and place, but the other side shows nothing
  there (``HoleReport``: candidates beyond the matched);
* ``FAINT_ONLY``: the darkest pixel of every mark is paler than ``marks.FAINT_DARKEST``;
* ``SHOW_THROUGH``: the marks are paler, mirrored copies of the other side's print (see ``bleed``);
* ``SET_OFF``: a neighbouring sheet's printed side rubbed off on a back (see ``bleed``; decided
  in the analysis, which sees the neighbours).

A page left out can have ``CREASE_IGNORED`` (the search for marks that ignores fold creases found
nothing, and the plain one finds something: a crease was ignored) and ``HOLES_MATCHED`` (every
mark is a hole the other side shows too). Only a page that stays has its marks' boxes.
"""

from dataclasses import dataclass

from fastfoto_linux.documents.bleed import show_through
from fastfoto_linux.documents.draft import BoxN, Flag
from fastfoto_linux.documents.holes import (
    EDGE_ZONE_MM,
    HoleReport,
    all_could_be_holes,
    hole_report,
)
from fastfoto_linux.documents.marks import BLANK_MARGIN_MM, FAINT_DARKEST, Mark, find_marks
from fastfoto_linux.documents.trim import Trimmed
from fastfoto_linux.documents.units import MM_PER_INCH

FEW_MARKS_MAX = 3  # a page with this many marks or fewer, and little ink, has few marks
FEW_MARKS_MM2 = 200.0  # ... their boxes together cover under this area (2 cm2)
HOLE_REPORT_MAX_MARKS = 12  # beyond this many marks a page is only weighed as holes if all could be
MAX_BOXES = 24  # a page keeps the boxes of its largest marks, no more


@dataclass(frozen=True)
class BlankVerdict:
    """Whether a page is blank and what that rests on: the ``marks`` found (creases ignored),
    the ``holes`` report (None: there was nothing to weigh, no marks or no partner) and whether
    a fold crease was ignored (only asked of a blank page)."""

    blank: bool
    marks: tuple[Mark, ...]
    holes: HoleReport | None
    crease_ignored: bool


@dataclass(frozen=True)
class PageAssessment:
    """The verdict of a page, the flags that explain it and, for a page that stays, the boxes of
    its marks (``MAX_BOXES`` at most)."""

    verdict: BlankVerdict
    flags: frozenset[Flag]
    marks: tuple[BoxN, ...]


def _crease_ignored(page: Trimmed, marks: tuple[Mark, ...]) -> bool:
    """Whether the plain search for marks finds one that ``marks`` (creases ignored) lack."""
    plain = find_marks(page.page, margin_mm=BLANK_MARGIN_MM, trimmed_bottom=page.tail_rows)
    return bool(set(plain) - set(marks))


def _weigh_holes(
    marks: tuple[Mark, ...], page: Trimmed, partner: Trimmed | None
) -> HoleReport | None:
    """The hole report, when it can matter: the verdict needs it only if every mark could be a
    hole, and the HOLE_LIKE flag only on a page with few marks (a dense page is print)."""
    if not marks or partner is None:
        return None
    if len(marks) > HOLE_REPORT_MAX_MARKS and not all_could_be_holes(marks, page):
        return None
    return hole_report(marks, page, partner)


def blank_verdict(page: Trimmed, partner: Trimmed | None) -> BlankVerdict:
    """Whether ``page`` is blank, its sheet's other side being ``partner`` (None: it has none).
    The rule is that of ``blank.is_blank_beside``."""
    marks = find_marks(
        page.page,
        margin_mm=BLANK_MARGIN_MM,
        trimmed_bottom=page.tail_rows,
        ignore_faint_lines=True,
    )
    report = _weigh_holes(marks, page, partner)
    blank = not marks or (report is not None and report.all_matched)
    return BlankVerdict(blank, marks, report, blank and _crease_ignored(page, marks))


def _area_mm2(marks: tuple[Mark, ...], dpi: int) -> float:
    pixels = sum((mark.x1 - mark.x0) * (mark.y1 - mark.y0) for mark in marks)
    return pixels * (MM_PER_INCH / dpi) ** 2


def _edge_mm(mark: Mark, page: Trimmed) -> float:
    height, width = page.page.pixels.shape[:2]
    edge = min(mark.x0, mark.y0, width - mark.x1, height - mark.y1)
    return edge * MM_PER_INCH / page.page.dpi


def _darkest(mark: Mark, page: Trimmed) -> int:
    return int(page.page.pixels[mark.y0 : mark.y1, mark.x0 : mark.x1].min())


def _kept_flags(verdict: BlankVerdict, page: Trimmed, partner: Trimmed | None) -> set[Flag]:
    marks = verdict.marks
    flags: set[Flag] = set()
    if len(marks) <= FEW_MARKS_MAX and _area_mm2(marks, page.page.dpi) < FEW_MARKS_MM2:
        flags.add(Flag.FEW_MARKS)
    if all(_edge_mm(mark, page) <= EDGE_ZONE_MM for mark in marks):
        flags.add(Flag.EDGE_ONLY)
    if verdict.holes is not None and verdict.holes.candidates > verdict.holes.matched:
        flags.add(Flag.HOLE_LIKE)
    if all(_darkest(mark, page) > FAINT_DARKEST for mark in marks):
        flags.add(Flag.FAINT_ONLY)
    if partner is not None and show_through(marks, page, partner):
        flags.add(Flag.SHOW_THROUGH)
    return flags


def _dropped_flags(verdict: BlankVerdict) -> set[Flag]:
    flags: set[Flag] = set()
    if verdict.crease_ignored:
        flags.add(Flag.CREASE_IGNORED)
    if verdict.holes is not None and verdict.holes.all_matched:
        flags.add(Flag.HOLES_MATCHED)
    return flags


def _boxes(marks: tuple[Mark, ...], page: Trimmed) -> tuple[BoxN, ...]:
    """The boxes of the largest ``MAX_BOXES`` marks as shares of the page, top to bottom."""
    height, width = page.page.pixels.shape[:2]
    largest = sorted(marks, key=lambda m: (m.x1 - m.x0) * (m.y1 - m.y0), reverse=True)
    chosen = sorted(largest[:MAX_BOXES], key=lambda m: (m.y0, m.x0))
    return tuple(BoxN(m.x0 / width, m.y0 / height, m.x1 / width, m.y1 / height) for m in chosen)


def assess_page(page: Trimmed, partner: Trimmed | None) -> PageAssessment:
    """The verdict on ``page`` (``blank_verdict``) and the flags and mark boxes that explain it."""
    verdict = blank_verdict(page, partner)
    if verdict.blank:
        return PageAssessment(verdict, frozenset(_dropped_flags(verdict)), ())
    flags = frozenset(_kept_flags(verdict, page, partner))
    return PageAssessment(verdict, flags, _boxes(verdict.marks, page))
