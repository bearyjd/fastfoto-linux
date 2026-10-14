"""Common photo-print formats, used to sanity-check a detected photo box."""

from fastfoto_linux.pipeline.geometry import MM_PER_INCH

# (short side, long side) in inches
PRINT_SIZES_INCH = (
    (3.5, 5.0),
    (4.0, 6.0),
    (4.0, 6.5),
    (5.0, 7.0),
    (6.0, 8.0),
    (8.0, 10.0),
    (8.0, 12.0),
)
SIZE_TOLERANCE_MM = 5.0  # per side; real 5x7 prints scan 2-3 mm larger than nominal
SQUARE_TOLERANCE_MM = 5.0  # any print whose sides differ by less than this counts as square
PANORAMA_MIN_ASPECT = 2.4  # long side / short side
PANORAMA_MIN_LONG_MM = 230.0

PRINT_SIZES_MM = tuple(
    (short * MM_PER_INCH, long * MM_PER_INCH) for short, long in PRINT_SIZES_INCH
)


def is_common_print_size(w_mm: float, h_mm: float) -> bool:
    """True if the size matches a common print format, a square, or a panorama (either way up)."""
    short, long = sorted((w_mm, h_mm))
    if long - short <= SQUARE_TOLERANCE_MM:
        return True
    if long / short >= PANORAMA_MIN_ASPECT and long >= PANORAMA_MIN_LONG_MM:
        return True
    return any(
        abs(short - nominal_short) <= SIZE_TOLERANCE_MM
        and abs(long - nominal_long) <= SIZE_TOLERANCE_MM
        for nominal_short, nominal_long in PRINT_SIZES_MM
    )
