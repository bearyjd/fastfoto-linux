"""Structure-only checks of the pairing on the private 8-page duplex batch (never run in CI).

Assertions are on counts, page numbers, booleans and millimetre sizes only: no pixel values,
text or paths are ever put into a failure message.
"""

import re
from functools import cache
from pathlib import Path

import pytest

from fastfoto_linux.pipeline.geometry import px_to_mm
from fastfoto_linux.pipeline.sides import BackPolicy, assemble_photos

pytestmark = pytest.mark.real_scans

EXPECTED_PAGES = 8
HANDWRITTEN_SHEETS = ({5, 6}, {7, 8})
PLAIN_SHEETS = ({1, 2}, {3, 4})
MAX_FRONT_BACK_SIZE_DIFF_MM = 3.0


def _page_numbers(photo) -> set[int]:
    return {int(re.search(r"(\d+)", page.stem).group(1)) for page in photo.source_pages}


@cache
def _assembled(scans_dir: Path):
    """Assemble once: every test below reads the same photos (this loads 8 full-size pages)."""
    pages = sorted(scans_dir.glob("photo-*.png"))
    assert len(pages) == EXPECTED_PAGES, f"expected {EXPECTED_PAGES} pages, found {len(pages)}"
    return assemble_photos(pages, duplex=True, back_policy=BackPolicy.ALWAYS)


@pytest.fixture
def photos(real_scans_dir):
    return _assembled(real_scans_dir)


def test_eight_pages_make_four_photos(photos) -> None:
    assert len(photos) == EXPECTED_PAGES // 2
    assert [_page_numbers(p) for p in photos] == [{1, 2}, {3, 4}, {5, 6}, {7, 8}]


def test_every_front_is_the_even_page(photos) -> None:
    fronts = [int(re.search(r"(\d+)", p.source_pages[0].stem).group(1)) for p in photos]
    assert all(number % 2 == 0 for number in fronts), f"front pages: {fronts}"


def test_only_the_last_two_sheets_have_writing(photos) -> None:
    writing = {frozenset(_page_numbers(p)) for p in photos if p.back_has_writing}
    plain = {frozenset(_page_numbers(p)) for p in photos if not p.back_has_writing}
    assert writing == {frozenset(s) for s in HANDWRITTEN_SHEETS}
    assert plain == {frozenset(s) for s in PLAIN_SHEETS}


def test_front_and_back_crops_have_the_same_size(photos) -> None:
    for photo in photos:
        assert photo.back is not None
        h_diff = abs(px_to_mm(photo.front.shape[0] - photo.back.shape[0], photo.dpi))
        w_diff = abs(px_to_mm(photo.front.shape[1] - photo.back.shape[1], photo.dpi))
        assert max(h_diff, w_diff) <= MAX_FRONT_BACK_SIZE_DIFF_MM, (
            f"photo {photo.index}: size differs by {w_diff:.1f} x {h_diff:.1f} mm"
        )


def test_no_real_sheet_is_uncertain(photos) -> None:
    assert not any(p.side_uncertain for p in photos)
