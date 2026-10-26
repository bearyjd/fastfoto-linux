"""The numbers of despeckle, in micrometres and counts, and their whole-pixel forms."""

SPECK_MAX_UM = 300  # a speck is at most 0.30 mm wide and high
GUARD_UM = 2500  # and has no other ink within 2.5 mm of its box
MIN_DPI = 150  # below this the pixels are too coarse to tell a speck from a stroke
MAX_SPECKS = 1000  # more removable specks than this in round 1: the page is not dust
MAX_ROUNDS = 4  # removal rounds before the page counts as unstable
SPECK_CHROMA = 40  # a component with a pixel this colourful (max - min of RGB) is deliberate
BAND_ROWS = 512  # most rows decided at a time
# Most pixels a band labels, its guard rows included: a wide page gets fewer rows per band, and a
# page too wide for even one row of the window is left alone. A4 at 600 dpi (3.2 million) keeps
# its 512 rows; one band then needs about 100 MiB at worst (a dot on every other pixel).
MAX_BAND_PIXELS = 6_000_000
# The bands of a page label at most this many times its area (guard rows are labelled again by
# the next band); a page that would need more is left alone, unless it is labelled whole.
BAND_OVERLAP = 4
# Pixels of the page at full resolution: it works there, not on cleanup's coarser work grid. About
# A3 at 600 dpi (69.6 million) with room to spare; the page-sized arrays (about 4 bytes a pixel,
# 6 with a colour source) then stay near 0.5 GB. Larger pages are left as they are.
MAX_DESPECKLE_PIXELS = 80_000_000
CONNECTIVITY = 8

_UM_PER_INCH = 25400


def speck_px(dpi: int) -> int:
    """The largest whole pixel count that is not over ``SPECK_MAX_UM`` (floor)."""
    return (SPECK_MAX_UM * dpi) // _UM_PER_INCH


def guard_px(dpi: int) -> int:
    """The smallest whole pixel count that is not under ``GUARD_UM`` (ceiling)."""
    return -(-(GUARD_UM * dpi) // _UM_PER_INCH)
