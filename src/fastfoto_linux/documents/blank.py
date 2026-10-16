"""Decide whether a page is blank (a duplex back with nothing on it)."""

from fastfoto_linux.documents.loader import LoadedPage


def is_blank(page: LoadedPage) -> bool:
    """True only when the page holds no mark at all inside its 5 mm margin.

    One confident mark keeps the page, so a signature, a short line, or a page number alone is
    not blank. When in doubt the answer is False.
    """
    raise NotImplementedError
