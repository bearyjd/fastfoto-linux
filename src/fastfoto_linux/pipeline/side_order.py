"""Which page of a duplex sheet is the front: paper content first, page order as the tie-break."""

from collections.abc import Sequence
from dataclasses import dataclass

# Two scores closer than this cannot tell the sides apart. Of 1374 real duplex sheets, 1322 have a
# back at 0.88 or more against a front 0.2 or more lower; 37 are ties by this margin.
PAPER_TIE_MARGIN = 0.2
# Content is trusted only when the paper-whiter page reaches this. Real backs of clear sheets are
# at 0.88 or more, but real fronts are not always below it (7 of 5182 reach 0.75, the maximum is
# 0.965), and 15 of 1374 real sheets have a dark or coloured back page that scores below a front.
# With both pages below it the lower score proves nothing; ``decide_sides`` then falls back to
# page order. That flags 11 of those 15 inversions and none of the 1322 clear sheets.
BACK_LIKE_PAPER_SCORE = 0.75
DEFAULT_FRONT_FIRST = True  # tie with no expectation and no resolved sheet: page 1 is the front
TIE_BREAK_RECENT_SHEETS = 8  # a tie follows the page order of this many latest confident sheets


@dataclass(frozen=True)
class SideDecision:
    """The front page of a sheet (0 or 1), whether that is doubtful and why, in words."""

    front_at: int
    uncertain: bool
    note: str | None = None


def _majority(recent: Sequence[bool]) -> bool | None:
    """The page order most of ``recent`` had (True: front first), or None for an even split."""
    front_first = sum(recent)
    back_first = len(recent) - front_first
    if front_first == back_first:
        return None
    return front_first > back_first


def _tie_break(expect_front_first: bool | None, recent: Sequence[bool]) -> tuple[bool, str]:
    """Front-first or not for a sheet content cannot decide, and where that answer came from."""
    if expect_front_first is not None:
        return expect_front_first, "the expected"
    majority = _majority(recent)
    if majority is not None:
        return majority, "the recent-sheets majority"
    return DEFAULT_FRONT_FIRST, "the default"


def _by_content(front_at: int, expect_front_first: bool | None) -> SideDecision:
    """The content's call; it still wins against ``expect_front_first`` but is then doubtful."""
    if expect_front_first is None or (front_at == 0) == expect_front_first:
        return SideDecision(front_at, False)
    note = (
        f"the content says page {front_at + 1} is the front, which contradicts "
        f"expect_front_first={expect_front_first}; using the content and keeping the back"
    )
    return SideDecision(front_at, True, note)


def decide_sides(
    scores: tuple[float, float], expect_front_first: bool | None, recent: Sequence[bool]
) -> SideDecision:
    """Which page of a sheet (0 or 1) is the front, from the paper scores of its two pages.

    The page with the lower score is the front when the scores differ by ``PAPER_TIE_MARGIN`` and
    the higher one reaches ``BACK_LIKE_PAPER_SCORE``. Otherwise (a tie, or no page that looks like
    a back) page order decides: ``expect_front_first``, else the majority of ``recent`` (the
    front-first flags of the latest confident sheets), else ``DEFAULT_FRONT_FIRST``. The decision
    is ``uncertain`` after any fallback and when the content contradicts ``expect_front_first``.
    Nothing here raises: a wrong guess is flagged, never a lost photo.
    """
    first, second = scores
    if abs(first - second) >= PAPER_TIE_MARGIN and max(first, second) >= BACK_LIKE_PAPER_SCORE:
        return _by_content(0 if first < second else 1, expect_front_first)
    if abs(first - second) < PAPER_TIE_MARGIN:
        cause = f"paper scores {first:.2f} and {second:.2f} cannot tell front from back"
    else:
        cause = (
            f"paper scores {first:.2f} and {second:.2f}: neither page is as paper-white as a back "
            f"({BACK_LIKE_PAPER_SCORE:.2f})"
        )
    front_first, source = _tie_break(expect_front_first, recent)
    scanned = "first" if front_first else "second"
    note = f"{cause}; using {source} page parity (front scanned {scanned})"
    return SideDecision(0 if front_first else 1, True, note)
