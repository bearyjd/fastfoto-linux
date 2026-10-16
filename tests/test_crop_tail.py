"""``trim_tail``: only the scanner's white tail goes; a page that is white itself stays whole."""

import numpy as np
import pytest

from fastfoto_linux.pipeline.crop import trim_tail
from fastfoto_linux.pipeline.geometry import mm_to_px
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


def test_the_frame_is_not_modified_and_the_result_is_a_copy() -> None:
    frame, _ = make_frame(dpi=DPI)
    before = frame.copy()
    trimmed = trim_tail(frame, DPI)
    trimmed[:] = 0
    assert np.array_equal(frame, before)


def test_a_bad_resolution_is_refused() -> None:
    frame, _ = make_frame(dpi=DPI)
    with pytest.raises(ValueError, match="dpi"):
        trim_tail(frame, 0)
