"""The numbers of despeckle, in micrometres and counts, and their whole-pixel forms."""

SPECK_MAX_UM = 300  # a speck is at most 0.30 mm wide and high
GUARD_UM = 2500  # and has no other ink within 2.5 mm of its box
MIN_DPI = 150  # below this the pixels are too coarse to tell a speck from a stroke
MAX_SPECKS = 1000  # more removable specks than this in round 1: the page is not dust
MAX_ROUNDS = 4  # removal rounds before the page counts as unstable
SPECK_CHROMA = 40  # a component with a pixel this colourful (max - min of RGB) is deliberate
BAND_ROWS = 512  # rows decided at a time
CONNECTIVITY = 8

_UM_PER_INCH = 25400


def speck_px(dpi: int) -> int:
    """The largest whole pixel count that is not over ``SPECK_MAX_UM`` (floor)."""
    return (SPECK_MAX_UM * dpi) // _UM_PER_INCH


def guard_px(dpi: int) -> int:
    """The smallest whole pixel count that is not under ``GUARD_UM`` (ceiling)."""
    return -(-(GUARD_UM * dpi) // _UM_PER_INCH)
