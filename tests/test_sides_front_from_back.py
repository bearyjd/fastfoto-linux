"""Fronts whose own crop is wrong or missing take their box from the back (mirrored in x)."""

import logging

import numpy as np
import pytest

from fastfoto_linux.pipeline.crop import Box, Detection, detect_photo
from fastfoto_linux.pipeline.geometry import mm_to_px
from fastfoto_linux.pipeline.sides import (
    FRONT_BACK_SIZE_TOLERANCE_MM,
    FRONT_FROM_BACK_X_OFFSET_MM,
    BackPolicy,
    assemble_photos,
    front_needs_correction,
    mirrored_front_box,
)
from tests.crop_helpers import assert_box_matches
from tests.sides_helpers import SIDES_LOGGER, batch
from tests.synth import SKY_RGB, make_duplex_sheet

SKY_MM = 44
CORRECTED_TOLERANCE_MM = 2.0


def _detection(w_mm: float, h_mm: float, *, plausible: bool = True, dpi: int = 150) -> Detection:
    return Detection(Box(0, 0, mm_to_px(w_mm, dpi), mm_to_px(h_mm, dpi)), plausible)


# --- mirrored_front_box ----------------------------------------------------------------------


def test_mirrored_box_flips_x_adds_the_offset_and_keeps_y_and_size() -> None:
    box = mirrored_front_box(Box(100, 10, 800, 600), (1500, 1200, 3), 150)
    shift = mm_to_px(FRONT_FROM_BACK_X_OFFSET_MM, 150)
    assert box == Box(1200 - 900 + shift, 10, 800, 600)


def test_mirrored_box_is_clamped_to_the_front_frame() -> None:
    at_left = mirrored_front_box(Box(0, 0, 800, 600), (600, 1000, 3), 150)
    assert at_left.x + at_left.w <= 1000
    short = mirrored_front_box(Box(300, 100, 600, 700), (600, 1000, 3), 150)
    assert short.y + short.h <= 600
    off_left = mirrored_front_box(Box(300, 0, 700, 500), (600, 1000, 3), 150)
    assert off_left.x >= 0


@pytest.mark.parametrize("dpi", [150, 300])
def test_mirrored_box_lands_on_the_real_front_of_a_synthetic_sheet(dpi: int) -> None:
    (front, front_box), (_, back_box) = make_duplex_sheet(dpi=dpi)
    assert_box_matches(
        mirrored_front_box(back_box, front.shape, dpi), front_box, dpi, CORRECTED_TOLERANCE_MM
    )


# --- front_needs_correction ------------------------------------------------------------------


def test_matching_plausible_front_is_trusted() -> None:
    back = _detection(178, 127).box
    assert not front_needs_correction(_detection(178, 127), back, 150)
    off = FRONT_BACK_SIZE_TOLERANCE_MM - 0.5
    assert not front_needs_correction(_detection(178 + off, 127 - off), back, 150)


def test_missing_front_needs_the_back() -> None:
    assert front_needs_correction(None, _detection(178, 127).box, 150)


def test_implausible_front_needs_the_back() -> None:
    assert front_needs_correction(
        _detection(178, 127, plausible=False), _detection(178, 127).box, 150
    )


@pytest.mark.parametrize("w_mm,h_mm", [(178 + 4, 127), (178 - 4, 127), (178, 127 + 4), (178, 123)])
def test_front_sized_unlike_the_back_needs_the_back(w_mm: float, h_mm: float) -> None:
    assert front_needs_correction(_detection(w_mm, h_mm), _detection(178, 127).box, 150)


# --- the sky scenario at sheet level ---------------------------------------------------------


@pytest.mark.parametrize("dpi", [150, 300])
def test_sky_coloured_front_top_is_recovered_through_the_back(dpi: int) -> None:
    sheet = make_duplex_sheet(dpi=dpi, front={"sky_mm": SKY_MM})
    (front_frame, front_box), _ = sheet
    own = detect_photo(front_frame, dpi)  # the crop module alone loses the sky ...
    assert own.box.y > front_box.y + mm_to_px(SKY_MM / 2, dpi)
    pages, loader = batch([sheet], (False,), dpi)
    (photo,) = assemble_photos(pages, duplex=True, back_policy=BackPolicy.ALWAYS, loader=loader)
    tolerance = mm_to_px(CORRECTED_TOLERANCE_MM, dpi)  # ... the sheet-level result keeps it
    assert photo.front.shape[0] == pytest.approx(front_box.h, abs=tolerance)
    assert photo.front.shape[1] == pytest.approx(front_box.w, abs=tolerance)
    top = photo.front[
        mm_to_px(2, dpi) : mm_to_px(SKY_MM - 2, dpi), mm_to_px(2, dpi) : -mm_to_px(2, dpi)
    ]
    assert top.reshape(-1, 3).mean(axis=0) == pytest.approx(SKY_RGB, abs=3)


def test_the_correction_is_logged_at_info(caplog: pytest.LogCaptureFixture) -> None:
    sheet = make_duplex_sheet(dpi=150, front={"sky_mm": SKY_MM})
    pages, loader = batch([sheet], (False,), 150)
    with caplog.at_level(logging.INFO, logger=SIDES_LOGGER):
        assemble_photos(pages, duplex=True, loader=loader)
    assert any("mirrored" in r.getMessage() and r.levelno == logging.INFO for r in caplog.records)


def test_a_good_front_crop_is_left_alone(caplog: pytest.LogCaptureFixture) -> None:
    sheet = make_duplex_sheet(dpi=150)
    (front_frame, _), _ = sheet
    pages, loader = batch([sheet], (False,), 150)
    with caplog.at_level(logging.DEBUG, logger=SIDES_LOGGER):
        (photo,) = assemble_photos(pages, duplex=True, loader=loader)
    own = detect_photo(front_frame, 150).box
    assert photo.front.shape[:2] == (own.h, own.w)
    assert np.array_equal(photo.front, front_frame[own.y : own.y + own.h, own.x : own.x + own.w])
    assert not any("mirrored" in r.getMessage() for r in caplog.records)
