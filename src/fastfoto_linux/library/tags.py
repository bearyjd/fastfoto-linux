"""EXIF Orientation values this tool handles, as clockwise turns of the displayed image."""

from types import MappingProxyType

ORIENTATION_TAG = 0x0112  # IFD0
TAG_UPRIGHT = 1
TAG_ROTATED_180 = 3
TAG_ROTATED_90_CW = 6
TAG_ROTATED_270_CW = 8
MIN_TAG = 1
MAX_TAG = 8
FULL_TURN = 360
# The clockwise angle a viewer turns the stored pixels by to show the photo the right way up.
CLOCKWISE_BY_TAG = MappingProxyType(
    {TAG_UPRIGHT: 0, TAG_ROTATED_90_CW: 90, TAG_ROTATED_180: 180, TAG_ROTATED_270_CW: 270}
)
TAG_BY_CLOCKWISE = MappingProxyType({angle: tag for tag, angle in CLOCKWISE_BY_TAG.items()})
QUARTER_TURNS = tuple(sorted(CLOCKWISE_BY_TAG.values()))
MIRRORED_TAGS = frozenset({2, 4, 5, 7})


def compose_tag(old_tag: int, extra_cw: int) -> int:
    """The tag that shows the photo ``extra_cw`` degrees further clockwise than ``old_tag`` does.

    ``old_tag`` must be 1, 3, 6 or 8 and ``extra_cw`` a multiple of 90; otherwise ValueError.
    """
    if old_tag not in CLOCKWISE_BY_TAG:
        raise ValueError(f"orientation tag {old_tag} cannot be combined with a turn")
    if extra_cw not in QUARTER_TURNS:
        raise ValueError(f"a turn must be one of {QUARTER_TURNS} degrees, got {extra_cw}")
    return TAG_BY_CLOCKWISE[(CLOCKWISE_BY_TAG[old_tag] + extra_cw) % FULL_TURN]
