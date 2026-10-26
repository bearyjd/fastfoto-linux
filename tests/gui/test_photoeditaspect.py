"""Crop shapes: the pure integer geometry behind the photo editor's aspect presets."""

import math
import re
from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.gui import photoeditaspect
from fastfoto_linux.gui.photoeditaspect import (
    PRESETS,
    aspect_crop,
    ceil_div,
    crop_ratio,
    default_portrait,
    fit_centred,
    half_up,
    swap_box,
)

FREE_MIN = (1, 1)
RATIOS = [(1, 1), (4, 3), (3, 4), (3, 2), (2, 3), (16, 9), (9, 16), (7, 5), (5, 7), (13, 3)]


def fit(box, ratio, frame, minimum=FREE_MIN):
    return fit_centred(box, ratio, frame=frame, minimum=minimum)


def test_the_presets_are_the_decided_ones_in_the_decided_order():
    assert [(p.id, p.label) for p in PRESETS] == [
        ("free", "Free"),
        ("original", "Original"),
        ("1:1", "1:1"),
        ("4:3", "4:3"),
        ("3:2", "3:2"),
        ("16:9", "16:9"),
        ("5:7", "5:7"),
    ]
    assert [(p.long, p.short) for p in PRESETS] == [
        (0, 0),
        (0, 0),
        (1, 1),
        (4, 3),
        (3, 2),
        (16, 9),
        (7, 5),
    ]


def test_the_module_needs_neither_qt_nor_numpy():
    text = Path(photoeditaspect.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:import|from)\s+(?:PySide6|numpy)", text, re.M)


@pytest.mark.parametrize(
    ("n", "d", "want"),
    [(5, 2, 3), (7, 2, 4), (1, 2, 1), (9, 2, 5), (0, 5, 0), (10, 4, 3), (3, 7, 0)],
)
def test_half_up_rounds_halves_up_where_round_goes_to_even(n, d, want):
    assert half_up(n, d) == want


def test_ceil_div():
    assert [ceil_div(7, 2), ceil_div(8, 2), ceil_div(1, 5), ceil_div(0, 3)] == [4, 4, 1, 0]


def expected_ratio(long, short, portrait, quarter_turns):
    dw, dh = (short, long) if portrait else (long, short)
    rw, rh = (dh, dw) if quarter_turns % 2 else (dw, dh)
    divisor = math.gcd(rw, rh)
    return rw // divisor, rh // divisor


@pytest.mark.parametrize(
    ("preset", "long", "short"),
    [("1:1", 1, 1), ("4:3", 4, 3), ("3:2", 3, 2), ("16:9", 16, 9), ("5:7", 7, 5)],
)
@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_crop_ratio_is_the_output_shape_seen_in_the_unturned_frame(
    preset, long, short, portrait, turns
):
    got = crop_ratio(preset, portrait, frame=(4000, 3000), quarter_turns=turns)
    assert got == expected_ratio(long, short, portrait, turns)


def test_crop_ratio_worked_cases():
    frame = (4000, 3000)
    assert crop_ratio("4:3", False, frame=frame, quarter_turns=0) == (4, 3)
    assert crop_ratio("4:3", True, frame=frame, quarter_turns=0) == (3, 4)
    assert crop_ratio("4:3", False, frame=frame, quarter_turns=1) == (3, 4)
    assert crop_ratio("5:7", False, frame=frame, quarter_turns=0) == (7, 5)
    assert crop_ratio("5:7", True, frame=frame, quarter_turns=0) == (5, 7)
    assert crop_ratio("5:7", True, frame=frame, quarter_turns=3) == (7, 5)


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_one_to_one_ignores_orientation_and_turns(turns):
    for portrait in (False, True):
        assert crop_ratio("1:1", portrait, frame=(400, 300), quarter_turns=turns) == (1, 1)


def test_free_has_no_ratio_and_an_unknown_shape_is_refused():
    assert crop_ratio("free", False, frame=(400, 300), quarter_turns=0) is None
    assert crop_ratio("free", True, frame=(400, 300), quarter_turns=1) is None
    with pytest.raises(ValueError, match="unknown crop shape"):
        crop_ratio("2:1", False, frame=(400, 300), quarter_turns=0)


@pytest.mark.parametrize("frame", [(4000, 3000), (3000, 4000), (4000, 2667), (500, 500), (90, 60)])
@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_original_on_an_uncropped_frame_never_double_swaps(frame, turns):
    fw, fh = frame
    portrait = default_portrait((0, 0, fw, fh), turns)
    divisor = math.gcd(fw, fh)
    got = crop_ratio("original", portrait, frame=frame, quarter_turns=turns)
    assert got == (fw // divisor, fh // divisor)


def test_original_follows_the_frame_and_keeps_a_gcd_one_ratio():
    assert crop_ratio("original", False, frame=(4000, 2667), quarter_turns=0) == (4000, 2667)
    assert crop_ratio("original", True, frame=(4000, 2667), quarter_turns=0) == (2667, 4000)
    assert crop_ratio("original", False, frame=(4000, 3000), quarter_turns=0) == (4, 3)


@pytest.mark.parametrize(
    ("box", "turns", "want"),
    [
        ((0, 0, 3, 4), 0, True),
        ((0, 0, 4, 3), 0, False),
        ((0, 0, 3, 3), 0, False),
        ((0, 0, 3, 4), 1, False),
        ((0, 0, 4, 3), 1, True),
        ((0, 0, 3, 3), 1, False),
        ((5, 5, 8, 9), 2, True),
        ((5, 5, 9, 8), 3, True),
        ((5, 5, 8, 9), 3, False),
    ],
)
def test_default_portrait_follows_the_output_and_square_is_landscape(box, turns, want):
    assert default_portrait(box, turns) is want


def test_fit_centred_worked_cases():
    assert fit((0, 0, 4000, 3000), (16, 9), (4000, 3000)) == (0, 375, 4000, 2625)
    assert fit((0, 0, 5, 4), (3, 2), (10, 10)) == (0, 0, 5, 3)
    assert fit((2, 3, 7, 7), (3, 2), (10, 10)) == (2, 3, 7, 6)
    assert fit((0, 0, 5, 3), (3, 2), (10, 10)) == (0, 0, 5, 3)


def test_fit_centred_floors_the_centring_offset():
    assert fit((0, 1, 5, 5), (3, 2), (10, 10)) == (0, 1, 5, 4)
    assert fit((3, 0, 8, 4), (3, 2), (10, 10)) == (3, 0, 8, 3)
    assert fit((3, 0, 9, 4), (1, 1), (10, 10)) == (4, 0, 8, 4)


def test_fit_centred_is_full_width_when_both_shapes_fill_the_box():
    assert fit((0, 0, 6, 4), (3, 2), (10, 10)) == (0, 0, 6, 4)
    assert fit((0, 0, 5, 3), (3, 2), (10, 10)) == (0, 0, 5, 3)


def test_fit_centred_rounds_the_other_side_half_up():
    assert fit((0, 0, 5, 9), (2, 1), (10, 10)) == (0, 3, 5, 6)
    assert fit((0, 0, 3, 9), (2, 3), (10, 10)) == (0, 2, 3, 7)


@pytest.mark.parametrize(
    ("box", "want"),
    [
        ((0, 0, 10, 10), (0, 0, 20, 20)),
        ((90, 90, 100, 100), (80, 80, 100, 100)),
        ((41, 41, 50, 50), (35, 35, 55, 55)),
        ((0, 40, 10, 50), (0, 35, 20, 55)),
        ((90, 40, 100, 50), (80, 35, 100, 55)),
    ],
)
def test_fit_centred_grows_to_the_minimum_centred_and_clamped(box, want):
    assert fit(box, (1, 1), (100, 100), minimum=(20, 20)) == want


def test_growth_may_reach_exactly_the_frame_edge_and_the_whole_frame():
    assert fit((10, 10, 30, 30), (1, 1), (50, 50), minimum=(50, 50)) == (0, 0, 50, 50)
    assert fit((0, 0, 30, 20), (3, 2), (60, 40), minimum=(60, 40)) == (0, 0, 60, 40)
    assert fit((10, 5, 40, 25), (3, 2), (60, 40), minimum=(45, 30)) == (2, 0, 47, 30)


def test_a_shape_that_cannot_reach_the_minimum_inside_the_frame_is_refused():
    assert fit((0, 0, 100, 40), (1, 1), (100, 40), minimum=(59, 59)) is None
    assert fit((0, 0, 30, 20), (16, 9), (30, 20), minimum=(30, 20)) is None


def test_original_on_a_tiny_frame_is_the_whole_frame():
    ratio = crop_ratio("original", False, frame=(6, 4), quarter_turns=0)
    assert ratio == (3, 2)
    assert fit((0, 0, 6, 4), ratio, (6, 4), minimum=(6, 4)) == (0, 0, 6, 4)


def random_case(rng):
    fw, fh = (int(v) for v in rng.integers(20, 400, size=2))
    left, right = sorted(int(v) for v in rng.integers(0, fw + 1, size=2))
    top, bottom = sorted(int(v) for v in rng.integers(0, fh + 1, size=2))
    right, bottom = max(right, left + 1), max(bottom, top + 1)
    box = (left, top, min(right, fw), min(bottom, fh))
    ratio = RATIOS[int(rng.integers(len(RATIOS)))]
    minimum = (int(rng.integers(1, fw // 2)), int(rng.integers(1, fh // 2)))
    return box, ratio, (fw, fh), minimum


def test_fit_centred_properties_over_random_cases():
    rng = np.random.default_rng(20261025)
    results = grown = 0
    for _ in range(2000):
        box, ratio, frame, minimum = random_case(rng)
        got = fit(box, ratio, frame, minimum)
        if got is None:
            continue
        results += 1
        rw, rh = ratio
        left, top, right, bottom = got
        w, h = right - left, bottom - top
        assert all(type(v) is int for v in got) and w >= minimum[0] and h >= minimum[1]
        assert 0 <= left < right <= frame[0] and 0 <= top < bottom <= frame[1]
        assert h == half_up(w * rh, rw) or w == half_up(h * rw, rh)
        assert fit(got, ratio, frame, minimum) == got
        inside = box[0] <= left and box[1] <= top and right <= box[2] and bottom <= box[3]
        if not inside:
            grown += 1
            continue
        bw, bh = box[2] - box[0], box[3] - box[1]
        for cw, ch in ((bw, half_up(bw * rh, rw)), (half_up(bh * rw, rh), bh)):
            if 1 <= cw <= bw and 1 <= ch <= bh:
                assert w * h >= cw * ch
    assert results > 1000 and grown > 20


def test_swap_box_transposes_the_size_and_keeps_the_centre():
    box = swap_box((100, 100, 500, 400), (3, 4), frame=(1000, 1000), minimum=FREE_MIN)
    assert box == (150, 50, 450, 450)


def test_swapping_twice_restores_the_box():
    once = swap_box((100, 100, 500, 400), (3, 4), frame=(1000, 1000), minimum=FREE_MIN)
    assert swap_box(once, (4, 3), frame=(1000, 1000), minimum=FREE_MIN) == (100, 100, 500, 400)


def test_a_swap_that_does_not_fit_is_cut_back_to_the_frame():
    assert swap_box((0, 0, 100, 50), (1, 2), frame=(100, 50), minimum=FREE_MIN) == (37, 0, 62, 50)


def test_a_swap_below_the_minimum_that_cannot_grow_is_refused():
    assert swap_box((0, 0, 100, 40), (1, 1), frame=(100, 40), minimum=(59, 59)) is None


def unclamped(box, frame):
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    x, y = (left + right - height) // 2, (top + bottom - width) // 2
    return 0 <= x <= frame[0] - height and 0 <= y <= frame[1] - width


def test_swap_box_properties_over_random_shaped_boxes():
    rng = np.random.default_rng(7)
    checked = 0
    for _ in range(1500):
        box, ratio, frame, _unused = random_case(rng)
        shaped = fit(box, ratio, frame)
        if shaped is None:
            continue
        rw, rh = ratio
        w, h = shaped[2] - shaped[0], shaped[3] - shaped[1]
        if h > frame[0] or w > frame[1]:
            continue
        swapped = swap_box(shaped, (rh, rw), frame=frame, minimum=FREE_MIN)
        assert swapped is not None
        assert (swapped[2] - swapped[0], swapped[3] - swapped[1]) == (h, w)
        assert swapped[0] >= 0 and swapped[2] <= frame[0] and swapped[1] >= 0
        assert swapped[3] <= frame[1]
        again = swap_box(swapped, (rw, rh), frame=frame, minimum=FREE_MIN)
        assert again is not None
        assert (again[2] - again[0], again[3] - again[1]) == (w, h)
        if unclamped(shaped, frame):  # clamping into the frame legitimately moves the box
            assert abs(again[0] - shaped[0]) <= 1 and abs(again[1] - shaped[1]) <= 1
        checked += 1
    assert checked > 500


SOURCE = {
    "min_width": 1,
    "min_height": 1,
    "source_width": 1000,
    "source_height": 600,
    "painted_width": 500,
    "painted_height": 300,
    "item_width": 500,
    "item_height": 300,
}


def drag(x0, y0, x1, y1, ratio=(4, 3), **changes):
    return aspect_crop(x0, y0, x1, y1, ratio=ratio, **{**SOURCE, **changes})


@pytest.mark.parametrize(
    ("press", "pointer", "want"),
    [
        ((50, 50), (150, 100), (100, 100, 300, 250)),
        ((150, 100), (50, 50), (100, 50, 300, 200)),
        ((50, 100), (150, 50), (100, 50, 300, 200)),
        ((150, 50), (50, 100), (100, 100, 300, 250)),
        ((50, 50), (80, 200), (100, 100, 500, 400)),
    ],
)
def test_a_ratio_drag_is_anchored_at_the_press_point_and_covers_the_drag(press, pointer, want):
    assert drag(*press, *pointer) == want


def test_the_anchor_is_floored_going_right_and_ceiled_going_left():
    assert drag(50.3, 50.3, 150, 100) == (100, 100, 300, 250)
    assert drag(150.3, 100.3, 50, 50) == (100, 50, 301, 201)


def test_a_drag_is_cut_back_from_the_anchor_to_fit_the_frame():
    assert drag(400, 200, 500, 300) == (800, 400, 1000, 550)
    assert drag(50, 250, 400, 300) == (100, 500, 233, 600)


def test_a_drag_outside_the_picture_is_clamped_and_letterboxing_is_honoured():
    boxed = {"painted_width": 400, "item_width": 600, "source_width": 800}
    assert drag(150, 50, 250, 150, (1, 1), **boxed) == (100, 100, 300, 300)
    assert drag(20, 50, 250, 150, (1, 1), **boxed) == (0, 100, 300, 400)
    assert drag(150, 50, 580, 150, (1, 1), **boxed) == (100, 100, 600, 600)


def test_a_drag_with_no_extent_or_under_the_minimum_gives_nothing():
    assert drag(50, 50, 50, 50) is None
    assert drag(50, 50, 150, 100, min_width=250) is None
    assert drag(50, 50, 150, 100, min_height=200) is None
    assert drag(50, 50, 150, 100, min_width=200, min_height=150) == (100, 100, 300, 250)


@pytest.mark.parametrize(
    "bad",
    [
        {"x0": math.nan},
        {"y1": math.inf},
        {"source_width": 0},
        {"source_height": -1},
        {"painted_width": 0},
        {"painted_height": 0},
        {"item_width": 0},
        {"item_height": math.nan},
    ],
)
def test_an_unusable_canvas_or_pointer_gives_nothing(bad):
    args = {"x0": 50, "y0": 50, "x1": 150, "y1": 100, **SOURCE, **bad}
    assert aspect_crop(**args, ratio=(4, 3)) is None


def test_a_non_positive_ratio_gives_nothing():
    assert drag(50, 50, 150, 100, (0, 3)) is None
    assert drag(50, 50, 150, 100, (4, 0)) is None


def test_ratio_drags_are_always_fixed_points_of_the_fit():
    rng = np.random.default_rng(99)
    produced = 0
    for _ in range(1000):
        sw, sh = (int(v) for v in rng.integers(50, 600, size=2))
        pw = float(rng.uniform(50, 400))
        ph = float(rng.uniform(50, 400))
        iw, ih = pw + float(rng.uniform(0, 100)), ph + float(rng.uniform(0, 100))
        mn = (int(rng.integers(1, 20)), int(rng.integers(1, 20)))
        ratio = RATIOS[int(rng.integers(len(RATIOS)))]
        xs = [float(v) for v in rng.uniform(-20, iw + 20, size=2)]
        ys = [float(v) for v in rng.uniform(-20, ih + 20, size=2)]
        got = aspect_crop(
            xs[0],
            ys[0],
            xs[1],
            ys[1],
            ratio=ratio,
            min_width=mn[0],
            min_height=mn[1],
            source_width=sw,
            source_height=sh,
            painted_width=pw,
            painted_height=ph,
            item_width=iw,
            item_height=ih,
        )
        if got is None:
            continue
        produced += 1
        assert all(type(v) is int for v in got)
        assert 0 <= got[0] < got[2] <= sw and 0 <= got[1] < got[3] <= sh
        assert fit_centred(got, ratio, frame=(sw, sh), minimum=mn) == got
    assert produced > 300


def is_shaped(width, height, ratio):
    rw, rh = ratio
    return height == half_up(width * rh, rw) or width == half_up(height * rw, rh)


def test_growth_takes_the_smallest_width_whose_rounded_height_reaches_the_minimum():
    assert fit((0, 0, 59, 59), (4, 3), (78, 59), (59, 59)) == (0, 0, 78, 59)
    assert fit((0, 0, 59, 78), (3, 4), (59, 78), (59, 59)) == (0, 0, 59, 78)
    assert fit((0, 0, 50, 50), (3, 4), (59, 78), (59, 59)) == (0, 0, 59, 78)


def test_a_shaped_frame_sized_box_at_the_minimum_is_accepted_unchanged():
    for ratio in RATIOS:
        for fw in range(2, 50):
            for fh in range(2, 50):
                if is_shaped(fw, fh, ratio):
                    assert fit((0, 0, fw, fh), ratio, (fw, fh), (fw, fh)) == (0, 0, fw, fh)
                    assert fit((0, 0, fw, fh), ratio, (fw, fh), (fw - 1, fh - 1)) == (0, 0, fw, fh)


def test_fitting_finds_intermediate_sizes_not_only_full_width_or_height():
    assert fit((0, 0, 7, 3), (16, 9), (7, 3)) == (0, 0, 6, 3)
    assert swap_box((0, 0, 3, 7), (16, 9), frame=(7, 3), minimum=FREE_MIN) == (0, 0, 6, 3)


def test_fitting_is_the_largest_shaped_box_over_every_small_size():
    for ratio in RATIOS:
        for width in range(1, 25):
            for height in range(1, 25):
                best = max(
                    (
                        w * h
                        for w in range(1, width + 1)
                        for h in range(1, height + 1)
                        if is_shaped(w, h, ratio)
                    ),
                    default=0,
                )
                got = fit((0, 0, width, height), ratio, (width, height))
                area = 0 if got is None else (got[2] - got[0]) * (got[3] - got[1])
                assert area == best, (ratio, width, height, got)


def frame_drag(sw, sh, ratio, minimum=(1, 1)):
    return aspect_crop(
        0, 0, sw, sh, ratio=ratio,
        min_width=minimum[0], min_height=minimum[1], source_width=sw, source_height=sh,
        painted_width=sw, painted_height=sh, item_width=sw, item_height=sh,
    )  # fmt: skip


def test_a_full_frame_drag_keeps_a_frame_that_only_the_width_side_rounds_to():
    assert frame_drag(59, 78, (3, 4), (59, 59)) == (0, 0, 59, 78)
    assert frame_drag(3, 2, (4, 3)) == (0, 0, 3, 2)


def test_a_full_frame_drag_is_the_frame_whenever_fitting_accepts_it():
    for ratio in RATIOS:
        for sw in range(2, 40):
            for sh in range(2, 40):
                if is_shaped(sw, sh, ratio):
                    assert frame_drag(sw, sh, ratio) == (0, 0, sw, sh), (ratio, sw, sh)


def click_at(start, end=None):
    end = start if end is None else end
    return aspect_crop(
        start, start, end, end, ratio=(1, 1), min_width=1, min_height=1,
        source_width=5, source_height=5, painted_width=5, painted_height=5,
        item_width=5, item_height=5,
    )  # fmt: skip


def test_a_fractional_click_without_movement_is_like_an_integer_one():
    for at in (0.0, 2.0, 5.0, 0.5, 2.5, 4.999):
        assert click_at(at) is None, at
    assert click_at(0.5, 1.5) == (0, 0, 2, 2)
    assert click_at(2.5, 1.5) == (1, 1, 3, 3)


def test_a_drag_in_a_thin_room_takes_the_smallest_covering_width_not_the_widest():
    wide = {"source_width": 50, "source_height": 1, "painted_width": 50}
    got = aspect_crop(
        0, 0, 5, 1, ratio=(13, 3), min_width=1, min_height=1,
        painted_height=1, item_width=50, item_height=1, **{k: v for k, v in wide.items()},
    )  # fmt: skip
    assert got == (0, 0, 5, 1)
