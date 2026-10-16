"""Millimetres to pixels: every image-geometry threshold in this package is written in mm."""

MM_PER_INCH = 25.4


def mm_to_px(mm: float, dpi: float) -> int:
    """``mm`` at ``dpi`` as a whole number of pixels, rounded, never less than 1."""
    return max(1, round(mm * dpi / MM_PER_INCH))
