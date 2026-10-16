"""``trim_tail``: only the scanner's white tail goes; a page that is white itself stays whole."""

import numpy as np
import pytest

from fastfoto_linux.pipeline.crop import find_photo_box, trim_tail
from fastfoto_linux.pipeline.geometry import mm_to_px
from tests.crop_helpers import assert_box_matches
from tests.synth import GREY_BAND_MM, make_frame

DPI = 150
WORK_FACTOR = 2  # the tail search runs on a copy downsampled by round(dpi / 75)


def tail_row(box_bottom: int) -> int:
    """The first row of the synthetic tail: the paper's bottom plus the grey band."""
    return box_bottom + mm_to_px(GREY_BAND_MM, DPI)


@pytest.mark.parametrize("side", ["front", "back"])
def test_the_white_tail_is_cut_off_and_nothing_else(side) -> None:
    frame, box = make_frame(dpi=DPI, side=side)
    trimmed = trim_tail(frame, DPI)
    first_tail_row = tail_row(box.y + box.h)
    assert first_tail_row <= trimmed.shape[0] < first_tail_row + WORK_FACTOR
    assert trimmed.shape[1] == frame.shape[1]
    assert np.array_equal(trimmed, frame[: trimmed.shape[0]])


def test_a_frame_without_a_tail_comes_back_whole() -> None:
    frame, _ = make_frame(dpi=DPI, tail_mm=0.0)
    assert np.array_equal(trim_tail(frame, DPI), frame)


def test_a_page_as_wide_and_white_as_the_tail_keeps_its_paper() -> None:
    """A full-width white card has no grey band to tell it from a tail: it must not vanish."""
    frame, box = make_frame(
        dpi=DPI,
        side="back",
        photo_mm=(216, 150),
        offset_mm=(0, 0.5),
        right_margin_mm=0.0,
        grey_band_mm=0.0,
        imprint=False,
    )
    assert trim_tail(frame, DPI).shape[0] >= box.y + box.h


def test_the_result_is_a_read_only_view_so_no_pixels_are_copied() -> None:
    frame, _ = make_frame(dpi=DPI)
    before = frame.copy()
    trimmed = trim_tail(frame, DPI)
    assert np.shares_memory(trimmed, frame)
    assert trimmed.flags.writeable is False
    assert np.array_equal(frame, before)


def test_a_frame_that_is_not_trimmed_is_a_view_too() -> None:
    frame, _ = make_frame(dpi=DPI, tail_mm=0.0)
    trimmed = trim_tail(frame, DPI)
    assert np.shares_memory(trimmed, frame)
    assert trimmed.shape == frame.shape


def test_a_bad_resolution_is_refused() -> None:
    frame, _ = make_frame(dpi=DPI)
    with pytest.raises(ValueError, match="dpi"):
        trim_tail(frame, 0)


# --- a white page must never be mistaken for the tail ------------------------------------------
# These frames are 216 mm wide, as wide as the scanner's white tail, at 150 dpi.

CARD_GREY = 252  # card paper: as white as the tail for the purposes of the finder
BAND_GREY = (150, 150, 150)
CARD_TOP_MM = 30.0
INK_GREY = 110
INK_LINE_MM, INK_PITCH_MM = 7.0, 11.0
INK_SPAN_MM = (20.0, 180.0)
MIN_BAND_MM = 6.0


def mm(value: float) -> int:
    return mm_to_px(value, DPI)


def blank_frame(total_mm: float) -> np.ndarray:
    frame = np.empty((mm(total_mm), mm(216.0), 3), np.uint8)
    frame[:] = (202, 210, 219)
    return frame


def card(frame: np.ndarray, top: float, bottom: float | None = None) -> None:
    frame[mm(top) : None if bottom is None else mm(bottom)] = CARD_GREY


def ink_lines(frame: np.ndarray, top: float, count: int) -> None:
    """``count`` lines of writing, each ``INK_LINE_MM`` tall, ``INK_PITCH_MM`` apart."""
    for line in range(count):
        first = mm(top + line * INK_PITCH_MM)
        frame[first : first + mm(INK_LINE_MM), mm(INK_SPAN_MM[0]) : mm(INK_SPAN_MM[1])] = INK_GREY


def band_and_tail(frame: np.ndarray, band_top: float, band_mm: float) -> None:
    frame[mm(band_top) : mm(band_top + band_mm)] = BAND_GREY
    frame[mm(band_top + band_mm) :] = 255


def test_handwriting_on_a_card_that_runs_to_the_frame_end_is_not_cut() -> None:
    frame = blank_frame(300.0)
    card(frame, CARD_TOP_MM)
    ink_lines(frame, 60.0, 3)
    assert trim_tail(frame, DPI).shape == frame.shape


@pytest.mark.parametrize("caption_top", [145.0, 200.0], ids=["right under", "far below"])
def test_a_photo_and_its_caption_on_a_card_are_not_cut(caption_top) -> None:
    frame = blank_frame(300.0)
    card(frame, CARD_TOP_MM)
    frame[mm(40.0) : mm(140.0), mm(30.0) : mm(186.0)] = 60
    ink_lines(frame, caption_top, 3)
    assert trim_tail(frame, DPI).shape == frame.shape


def test_a_photo_on_a_card_with_nothing_below_it_is_not_cut() -> None:
    frame = blank_frame(300.0)
    card(frame, CARD_TOP_MM)
    frame[mm(40.0) : mm(140.0), mm(30.0) : mm(186.0)] = 60
    assert trim_tail(frame, DPI).shape == frame.shape


@pytest.mark.parametrize("band_mm", [8.0, 9.0])
def test_a_card_followed_by_the_band_and_the_tail_keeps_every_row_of_the_card(band_mm) -> None:
    frame = blank_frame(340.0)
    card(frame, CARD_TOP_MM, 280.0)
    ink_lines(frame, 60.0, 3)
    band_and_tail(frame, 280.0, band_mm)
    trimmed = trim_tail(frame, DPI)
    tail_start = mm(280.0 + band_mm)
    assert tail_start <= trimmed.shape[0] < tail_start + WORK_FACTOR
    assert np.array_equal(trimmed, frame[: trimmed.shape[0]])


def test_a_band_thinner_than_the_minimum_is_not_enough_to_cut_anything() -> None:
    frame = blank_frame(340.0)
    card(frame, CARD_TOP_MM, 280.0)
    band_and_tail(frame, 280.0, MIN_BAND_MM - 1.0)
    assert trim_tail(frame, DPI).shape == frame.shape


def test_a_white_run_that_does_not_reach_the_frame_end_is_not_a_tail() -> None:
    frame = blank_frame(340.0)
    card(frame, CARD_TOP_MM, 280.0)
    band_and_tail(frame, 280.0, 9.0)
    frame[mm(320.0) :] = 90  # 31 mm of dirt under the white: whatever this is, it is not padding
    assert trim_tail(frame, DPI).shape == frame.shape


def test_the_tail_finder_is_stricter_than_the_photo_finder_about_dirt() -> None:
    """The photo path still shrugs off an 8 mm streak in the tail; trimming stops at it."""
    frame, box = make_frame(dpi=DPI, tail_mm=100.0)
    streak_top = box.y + box.h + mm(GREY_BAND_MM + 40.0)
    frame[streak_top : streak_top + mm(8.0)] = 90
    assert_box_matches(find_photo_box(frame, DPI), box, DPI)
    trimmed = trim_tail(frame, DPI)
    assert streak_top + mm(8.0) <= trimmed.shape[0] < streak_top + mm(8.0) + WORK_FACTOR
