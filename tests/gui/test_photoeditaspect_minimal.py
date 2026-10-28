"""Crop shapes: minimal covering drags, micro-pixel rounding like the canvas, minimal growth."""

import math

import pytest

from fastfoto_linux.gui import photoeditaspect
from fastfoto_linux.gui.photoeditaspect import PRESETS, aspect_crop, half_up
from fastfoto_linux.gui.photoeditcoords import micro, source_crop


def is_shaped(width, height, ratio):
    rw, rh = ratio
    return height == half_up(width * rh, rw) or width == half_up(height * rw, rh)


def test_a_covering_drag_takes_the_least_width_whose_rounded_height_reaches_it():
    got = aspect_crop(
        0, 0, 0.5, 3, ratio=(3, 2), min_width=1, min_height=1, source_width=100,
        source_height=100, painted_width=100, painted_height=100, item_width=100,
        item_height=100,
    )  # fmt: skip
    assert got == (0, 0, 4, 3)  # half_up(4 * 2, 3) == 3 already covers dy; 5 was one too wide


@pytest.mark.parametrize("ratio", [(r.long, r.short) for r in PRESETS if r.long] + [(5, 7)])
def test_a_covering_drag_is_the_minimal_width_shaped_box_over_small_drags(ratio):
    rw, rh = ratio
    for dx in range(0, 13):
        for dy in range(0, 13):
            if dx == 0 and dy == 0:
                continue
            got = aspect_crop(
                0, 0, dx, dy, ratio=ratio, min_width=1, min_height=1, source_width=200,
                source_height=200, painted_width=200, painted_height=200, item_width=200,
                item_height=200,
            )  # fmt: skip
            want = next(w for w in range(1, 400) if w >= dx and half_up(w * rh, rw) >= dy)
            assert got == (0, 0, want, half_up(want * rh, rw)), (ratio, dx, dy)


def test_the_micro_helper_rounds_half_up_like_javascript():
    assert micro(0.0000005) == 0.000001  # round(v, 6) goes to the even digit here: 0.0
    assert micro(2.5000005) == 2.500001
    assert micro(-0.25) == -0.25


def js_round(value):
    return math.floor(value * 1e6 + 0.5) / 1e6


def tie_value():
    """A pixel position whose round(v, 6) and half-up rounding disagree about its floor."""
    for k in range(1, 7):
        v = k + 0.9999995
        if math.floor(round(v, 6)) != math.floor(js_round(v)):
            return v
    raise AssertionError("no tie value found")


def test_a_tie_value_is_read_as_javascript_reads_it_by_the_drag_and_the_source_crop():
    v = tie_value()
    source = 8  # a power of two: the pointer maps to ``v`` exactly, so the tie survives
    common = {"min_width": 1, "min_height": 1, "source_width": source, "source_height": source}
    common |= {"painted_width": source, "painted_height": source}
    common |= {"item_width": source, "item_height": source}
    # The JS reference: the press lands at js_round(v), so the box starts at its floor.
    got = aspect_crop(v, 0, source, 1, ratio=(1, 1), **common)
    assert got is not None and got[0] == math.floor(js_round(v))
    anchored = source_crop(v, v, source, source, **common)
    assert anchored is not None and anchored[0] == math.floor(js_round(v))


def min_area_grown(ratio, minimum, frame):
    shaped = {
        (w, h)
        for w in range(1, frame[0] + 1)
        for h in range(1, frame[1] + 1)
        if is_shaped(w, h, ratio)
    }
    found = [(w, h) for w, h in shaped if w >= minimum[0] and h >= minimum[1]]
    return min((w * h for w, h in found), default=None)


def test_growth_picks_the_smaller_area_when_the_height_first_candidate_is_smaller():
    assert photoeditaspect._grown((3, 4), (59, 59), (5000, 5000)) == (59, 78)


@pytest.mark.parametrize("ratio", [(r.long, r.short) for r in PRESETS if r.long] + [(5, 7)])
def test_growth_is_area_minimal_over_the_presets_and_small_minimums(ratio):
    rw, rh = ratio
    for ratio_form in (ratio, (rh, rw)):
        for lo in range(1, 41):
            for hi in (lo, 40):
                got = photoeditaspect._grown(ratio_form, (lo, hi), (400, 400))
                want = min_area_grown(ratio_form, (lo, hi), (400, 400))
                assert got != (0, 0) and got[0] * got[1] == want, (ratio_form, lo, hi, got)
                assert got[0] >= lo and got[1] >= hi and is_shaped(*got, ratio_form)
