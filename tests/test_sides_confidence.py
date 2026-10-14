"""When the content may decide which side is the front, and when only parity may."""

import numpy as np
import pytest

from fastfoto_linux.pipeline.sides import (
    TIE_BREAK_RECENT_SHEETS,
    BackPolicy,
    assemble_photos,
)
from tests.sides_helpers import Sheet, batch, page_number
from tests.synth import make_duplex_sheet

DPI = 150
WRITTEN = {"writing": True}
BLANK = {"imprint": False}
DARK_BACK = {"photo_rgb": (70, 70, 70), "imprint": False}  # a dark or coloured "back" page
NEAR_WHITE = (245, 245, 245)  # a front that scores exactly like a back


def _half_bright_front_sheet() -> Sheet:
    """A dark back and a front whose left half is bright: it scores about 0.5, well above the
    back's 0.0 but short of the paper level of a real back."""
    (front, box), back = make_duplex_sheet(dpi=DPI, back=DARK_BACK)
    front = front.copy()
    front[box.y : box.y + box.h, box.x : box.x + box.w // 2] = 240
    return (front, box), back


@pytest.mark.parametrize(
    ("front_first", "expect_front_first"),
    [(True, None), (False, None), (True, True), (False, False)],
)
def test_dark_back_against_a_bright_front_is_not_a_confident_swap(
    front_first: bool, expect_front_first: bool | None
) -> None:
    """Nothing here is paper-white, so the lower score proves nothing: parity decides, the sheet
    is flagged and NEVER may not drop what could be the real front."""
    pages, loader = batch([_half_bright_front_sheet()], (front_first,), DPI)
    (photo,) = assemble_photos(
        pages,
        duplex=True,
        back_policy=BackPolicy.NEVER,
        expect_front_first=expect_front_first,
        loader=loader,
    )
    assert photo.side_uncertain
    assert photo.back is not None
    expected_front_first = True if expect_front_first is None else expect_front_first
    assert tuple(map(page_number, photo.source_pages)) == (
        (1, 2) if expected_front_first else (2, 1)
    )


def test_a_paper_white_back_against_a_dark_page_is_still_a_confident_call() -> None:
    sheet = make_duplex_sheet(dpi=DPI, back=BLANK)
    pages, loader = batch([sheet], (False,), DPI)
    (photo,) = assemble_photos(pages, duplex=True, back_policy=BackPolicy.NEVER, loader=loader)
    assert not photo.side_uncertain
    assert photo.back is None
    assert tuple(map(page_number, photo.source_pages)) == (2, 1)


def test_content_against_an_explicit_parity_wins_but_keeps_the_back_under_never() -> None:
    pages, loader = batch([make_duplex_sheet(dpi=DPI, back=BLANK)], (False,), DPI)
    (photo,) = assemble_photos(
        pages, duplex=True, back_policy=BackPolicy.NEVER, expect_front_first=True, loader=loader
    )
    assert tuple(map(page_number, photo.source_pages)) == (2, 1)  # the content, not the parity
    assert photo.side_uncertain
    assert photo.back is not None
    assert np.median(photo.front) < np.median(photo.back)


def test_content_agreeing_with_an_explicit_parity_stays_confident() -> None:
    pages, loader = batch([make_duplex_sheet(dpi=DPI, back=BLANK)], (False,), DPI)
    (photo,) = assemble_photos(
        pages, duplex=True, back_policy=BackPolicy.NEVER, expect_front_first=False, loader=loader
    )
    assert not photo.side_uncertain
    assert photo.back is None


# --- a tie follows the recent sheets, not the whole batch -------------------------------------


def _tie_after(older_front_first: bool) -> tuple[int, ...]:
    """Page numbers of the tie sheet's (front, back) after ``TIE_BREAK_RECENT_SHEETS + 2``
    sheets of one page order and then ``TIE_BREAK_RECENT_SHEETS`` of the other."""
    clear = make_duplex_sheet(dpi=DPI, back=WRITTEN)
    tie = make_duplex_sheet(dpi=DPI, front={"photo_rgb": NEAR_WHITE}, back=BLANK)
    older, recent = TIE_BREAK_RECENT_SHEETS + 2, TIE_BREAK_RECENT_SHEETS
    sheets = [clear] * (older + recent) + [tie]
    order = (older_front_first,) * older + (not older_front_first,) * recent + (True,)
    pages, loader = batch(sheets, order, DPI)
    photos = assemble_photos(pages, duplex=True, loader=loader)
    assert not any(p.side_uncertain for p in photos[:-1])
    assert photos[-1].side_uncertain
    return tuple(map(page_number, photos[-1].source_pages))


def test_a_tie_follows_a_stack_that_flipped_to_front_first() -> None:
    last = 2 * (2 * TIE_BREAK_RECENT_SHEETS + 2)  # page number before the tie sheet's pages
    assert _tie_after(older_front_first=False) == (last + 1, last + 2)


def test_a_tie_follows_a_stack_that_flipped_to_back_first() -> None:
    last = 2 * (2 * TIE_BREAK_RECENT_SHEETS + 2)
    assert _tie_after(older_front_first=True) == (last + 2, last + 1)
