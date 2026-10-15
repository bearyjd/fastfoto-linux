"""Orientation tags as clockwise turns: checked against Pillow's own reading of the tag."""

import numpy as np
import pytest

from fastfoto_linux.library.tags import CLOCKWISE_BY_TAG, compose_tag
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import (
    CLOCKWISE_BY_TAG as ORACLE_CLOCKWISE_BY_TAG,
)
from tests.library.jpeg_helpers import (
    displayed_array,
    exif_bytes,
    make_jpeg,
    rotate_cw,
    stored_array,
)

TAGS = (1, 3, 6, 8)
TURNS = (0, 90, 180, 270)


def test_the_tag_table_matches_what_a_viewer_does() -> None:
    """Pillow shows tag 6 by turning the stored pixels 90 degrees clockwise, and so on."""
    for tag in TAGS:
        data = make_jpeg(load_astronaut(), exif=exif_bytes(tag))
        shown = displayed_array(data)
        assert np.array_equal(shown, rotate_cw(stored_array(data), CLOCKWISE_BY_TAG[tag]))
    assert dict(CLOCKWISE_BY_TAG) == ORACLE_CLOCKWISE_BY_TAG


def test_tag_6_is_what_a_camera_writes_for_a_photo_held_on_its_right_side() -> None:
    """EXIF: 6 = the stored picture must be rotated 90 degrees clockwise to be upright."""
    upright = load_astronaut()
    sideways_ccw = np.ascontiguousarray(np.rot90(upright, k=1))  # turned counter-clockwise
    shown = displayed_array(make_jpeg(sideways_ccw, exif=exif_bytes(6)))
    assert shown.shape == upright.shape
    assert np.abs(shown.astype(int) - upright.astype(int)).mean() < 12


@pytest.mark.parametrize("old_tag", TAGS)
@pytest.mark.parametrize("extra", TURNS)
def test_composing_turns_the_displayed_photo_further_clockwise(old_tag: int, extra: int) -> None:
    data = make_jpeg(load_astronaut(), exif=exif_bytes(old_tag))
    new_tag = compose_tag(old_tag, extra)
    shown_before = displayed_array(data)
    after = make_jpeg(load_astronaut(), exif=exif_bytes(new_tag))
    assert np.array_equal(displayed_array(after), rotate_cw(shown_before, extra))


@pytest.mark.parametrize(
    ("old_tag", "extra", "expected"),
    [(1, 90, 6), (1, 180, 3), (1, 270, 8), (6, 90, 3), (8, 90, 1), (3, 180, 1), (6, 270, 1)],
)
def test_known_compositions(old_tag: int, extra: int, expected: int) -> None:
    assert compose_tag(old_tag, extra) == expected


@pytest.mark.parametrize(
    ("old_tag", "extra"), [(2, 90), (9, 0), (0, 0), (1, 45), (1, 360), (1, -90)]
)
def test_unsupported_combinations_are_rejected(old_tag: int, extra: int) -> None:
    with pytest.raises(ValueError, match=r"tag|turn"):
        compose_tag(old_tag, extra)
