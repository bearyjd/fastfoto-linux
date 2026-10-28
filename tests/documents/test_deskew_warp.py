"""The deskew warp: same frame, white fill, binary stays binary, and the sign is the reference's."""

import numpy as np
import pytest

from fastfoto_linux.documents.deskew_warp import deskewed
from fastfoto_linux.documents.modes import ColourMode
from tests.documents.deskew_fixtures import skewed, text_page


def _page() -> np.ndarray:
    return text_page(np.random.default_rng(1), dpi=100)


@pytest.mark.parametrize("tenths", [-100, -37, 5, 100])
def test_the_frame_is_unchanged(tenths: int) -> None:
    pixels = _page()
    assert deskewed(pixels, tenths, ColourMode.GREY).shape == pixels.shape


def test_the_input_is_not_modified() -> None:
    pixels = _page()
    before = pixels.copy()
    deskewed(pixels, 41, ColourMode.GREY)
    assert np.array_equal(pixels, before)


def test_the_corners_of_a_colour_page_are_white_on_every_channel() -> None:
    black = np.zeros((200, 150, 3), np.uint8)
    out = deskewed(black, 100, ColourMode.COLOUR)
    for y, x in ((0, 0), (0, 149), (199, 0), (199, 149)):
        assert tuple(out[y, x]) == (255, 255, 255)
    assert tuple(out[100, 75]) == (0, 0, 0)


def test_the_corners_of_a_grey_page_are_white() -> None:
    out = deskewed(np.zeros((200, 150), np.uint8), -100, ColourMode.GREY)
    assert out[0, 0] == out[199, 149] == 255


def test_a_one_bit_page_stays_zero_and_255() -> None:
    bw = np.where(_page() < 128, 0, 255).astype(np.uint8)
    out = deskewed(bw, 73, ColourMode.BW)
    assert set(np.unique(out)) <= {0, 255}


def test_a_positive_angle_turns_clockwise_like_the_reference() -> None:
    pixels = _page()
    for tenths in (-80, 47):
        ours = deskewed(pixels, tenths, ColourMode.GREY).astype(int)
        reference = skewed(pixels, tenths).astype(int)
        opposite = skewed(pixels, -tenths).astype(int)
        # the white fill differs from paper only in the wedges; compare the page's middle
        mid = (slice(30, -30), slice(30, -30))
        assert np.abs(ours[mid] - reference[mid]).mean() < 8
        assert np.abs(ours[mid] - opposite[mid]).mean() > 3 * np.abs(ours[mid] - reference[mid]).mean()


@pytest.mark.parametrize("bad", [101, -101, True, 1.5, "3"])
def test_a_bad_angle_is_refused(bad) -> None:
    with pytest.raises(ValueError, match="deskew"):
        deskewed(_page(), bad, ColourMode.GREY)
