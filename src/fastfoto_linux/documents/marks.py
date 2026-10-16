"""Find the marks on a page: letter-sized spots that clearly differ from the paper."""

from dataclasses import dataclass

from fastfoto_linux.documents.loader import LoadedPage


@dataclass(frozen=True)
class Mark:
    """Bounding box of one mark in page pixels (end exclusive)."""

    x0: int
    y0: int
    x1: int
    y1: int


def find_marks(page: LoadedPage, *, margin_mm: float = 0.0) -> tuple[Mark, ...]:
    """The marks on ``page`` that lie inside a margin of ``margin_mm`` on every side.

    A mark is a connected spot that is dark against the local paper tone (or very dark outright)
    and at least a letter's size; dust, paper texture and faint show-through are not marks.
    """
    raise NotImplementedError
