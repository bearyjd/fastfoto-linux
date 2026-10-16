"""Cut off what is certainly not paper: the scanner's white tail and a blue-grey backing strip."""

from dataclasses import dataclass

from fastfoto_linux.documents.loader import LoadedPage


@dataclass(frozen=True)
class Trimmed:
    """The page after trimming and how many pixels were removed from each side."""

    page: LoadedPage
    left: int
    right: int
    bottom: int


def trim_page(page: LoadedPage) -> Trimmed:
    """Trim the tail below the paper and backing strips beside it; when unsure, trim nothing.

    The input is not modified; the trimmed page may share memory with it.
    """
    raise NotImplementedError
