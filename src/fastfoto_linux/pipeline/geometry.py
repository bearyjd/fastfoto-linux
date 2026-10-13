"""Millimetre/pixel conversions so image-geometry thresholds are resolution independent."""


def mm_to_px(mm: float, dpi: float) -> int:
    """Convert a length in millimetres to the nearest whole number of pixels."""
    raise NotImplementedError


def px_to_mm(px: float, dpi: float) -> float:
    """Convert a length in pixels to millimetres."""
    raise NotImplementedError
