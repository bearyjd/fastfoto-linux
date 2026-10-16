"""Millimetres to pixels, and which mode a page of each kind is written in."""

import pytest

from fastfoto_linux.documents.modes import ColourMode, output_mode
from fastfoto_linux.documents.units import mm_to_px

C, G, B = ColourMode.COLOUR, ColourMode.GREY, ColourMode.BW


@pytest.mark.parametrize(
    ("mm", "dpi", "expected"),
    [(25.4, 300, 300), (25.4, 100, 100), (5, 300, 59), (1, 100, 4), (0.01, 300, 1), (0, 300, 1)],
)
def test_millimetres_become_pixels_rounded_and_never_zero(mm, dpi, expected) -> None:
    assert mm_to_px(mm, dpi) == expected


def test_the_same_length_scales_with_the_resolution() -> None:
    assert mm_to_px(10, 600) == 2 * mm_to_px(10, 300)


# A page can lose colour but never gain it (rows: what the page is; columns: what was asked).
@pytest.mark.parametrize(
    ("kind", "requested", "written"),
    [
        (C, C, C), (C, G, G), (C, B, B),
        (G, C, G), (G, G, G), (G, B, B),
        (B, C, B), (B, G, B), (B, B, B),
    ],
)  # fmt: skip
def test_a_page_never_gains_colour(kind, requested, written) -> None:
    assert output_mode(kind, requested) is written
