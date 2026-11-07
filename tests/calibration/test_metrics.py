"""The metric functions on hand-built arrays."""

import numpy as np
import pytest

from fastfoto_linux.evaluation.calib_metrics import (
    ciede2000,
    edge_width,
    flat_sigmas,
    halo_pct,
    luma,
    neutral_de00,
    proportion_entry,
    rounded,
    skew_error_deg,
    wrong_direction,
)


@pytest.mark.parametrize(
    ("one", "two", "expected"),  # Sharma, Wu and Dalal's published check pairs
    [
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
        ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
        ((50.0, 2.5, 0.0), (50.0, 0.0, -2.5), 4.3065),
        ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ],
)
def test_ciede2000_matches_the_published_pairs(one, two, expected) -> None:
    assert ciede2000(np.array(one), np.array(two)) == pytest.approx(expected, abs=1e-4)
    assert ciede2000(np.array(two), np.array(one)) == pytest.approx(expected, abs=1e-4)


def test_neutral_grey_has_no_error_and_a_cast_has_more_with_more_cast() -> None:
    grey = np.full((8, 8, 3), 120, np.uint8)
    mild, strong = grey.copy(), grey.copy()
    mild[..., 0] += 10
    strong[..., 0] += 40
    boxes = ((0, 0, 8, 8),)
    assert neutral_de00(grey, boxes) < 0.01
    assert 1 < neutral_de00(mild, boxes) < neutral_de00(strong, boxes)


def test_flat_sigma_is_the_luma_standard_deviation_per_box() -> None:
    img = np.zeros((4, 8, 3), np.uint8)
    img[:, 4:] = (10, 10, 10)
    assert flat_sigmas(luma(img), ((0, 0, 4, 4),)) == [0.0]
    assert flat_sigmas(luma(img), ((0, 0, 8, 4),))[0] == pytest.approx(5.0, abs=1e-6)


def ramp(low: float = 20.0, high: float = 220.0, lead: int = 10, steps: int = 10) -> np.ndarray:
    row = np.concatenate([np.full(lead, low), np.linspace(low, high, steps), np.full(lead, high)])
    return np.tile(row, (6, 1))


def test_edge_width_of_a_linear_ramp_is_eighty_percent_of_the_ramp() -> None:
    img = ramp()
    width = img.shape[1]
    assert edge_width(img, (0, 0, width, 6), "h") == pytest.approx(7.2, abs=0.01)  # 0.8 * 9
    assert edge_width(img[:, ::-1].copy(), (0, 0, width, 6), "h") == pytest.approx(7.2, abs=0.01)
    assert edge_width(img.T.copy(), (0, 0, 6, width), "v") == pytest.approx(7.2, abs=0.01)


def test_edge_width_of_a_flat_box_is_unknown() -> None:
    assert edge_width(np.full((6, 20), 50.0), (0, 0, 20, 6), "h") is None


def test_halo_is_the_overshoot_as_a_percent_of_the_edge_height() -> None:
    before = ramp()
    after = before.copy()
    after[:, 20:] += 10.0  # ten levels over a 200-level edge
    box = (0, 0, before.shape[1], 6)
    assert halo_pct(before, before, box, "h") == 0.0
    assert halo_pct(before, after, box, "h") == pytest.approx(5.0)
    undershoot = before.copy()
    undershoot[:, :5] -= 10.0
    assert halo_pct(before, undershoot, box, "h") == pytest.approx(5.0)


def test_skew_error_and_direction_follow_the_clockwise_correction_convention() -> None:
    assert skew_error_deg(-40, (-40,)) == 0.0
    assert skew_error_deg(-42, (-40, -38, -40)) == pytest.approx(0.2667, abs=0.001)
    assert skew_error_deg(30, (-30,)) == pytest.approx(6.0)
    assert wrong_direction(30, (-30,)) is True
    assert wrong_direction(-30, (-30,)) is False
    assert wrong_direction(-30, (0,)) is False  # no direction to get wrong


def test_rounding_is_four_places_through_nested_values() -> None:
    assert rounded({"a": [1.123456, 2], "b": {"c": 0.00004999}}) == {
        "a": [1.1235, 2],
        "b": {"c": 0.0},
    }


def test_proportion_entry_drops_the_note_and_keeps_the_zero_bound() -> None:
    zero = proportion_entry(0, 20)
    assert "note" not in zero and zero["zero_upper_bound"] == pytest.approx(0.1391, abs=1e-4)
    assert proportion_entry(1, 4)["p"] == 0.25
    assert proportion_entry(0, 0)["p"] is None
