"""Millimetre/pixel conversions so image-geometry thresholds are resolution independent."""

MM_PER_INCH = 25.4


def _require_positive_dpi(dpi: float) -> None:
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")


def mm_to_px(mm: float, dpi: float) -> int:
    """Convert a length in millimetres to the nearest whole number of pixels."""
    _require_positive_dpi(dpi)
    return round(mm * dpi / MM_PER_INCH)


def px_to_mm(px: float, dpi: float) -> float:
    """Convert a length in pixels to millimetres."""
    _require_positive_dpi(dpi)
    return px * MM_PER_INCH / dpi
