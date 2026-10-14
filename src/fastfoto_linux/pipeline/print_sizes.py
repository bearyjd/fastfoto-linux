"""Common photo-print formats, used to sanity-check a detected photo box."""


def is_common_print_size(w_mm: float, h_mm: float) -> bool:
    """True if the size matches a common print format, a square, or a panorama (either way up)."""
    raise NotImplementedError
