"""A coarse map of the dark on a page, to tell ink that comes from a neighbouring sheet (stub)."""

from collections.abc import Sequence

from fastfoto_linux.documents.draft import BoxN, InkMap
from fastfoto_linux.documents.trim import Trimmed

HIT_MIN = 0.9


def ink_map(page: Trimmed) -> InkMap:
    raise NotImplementedError


def hit_rates(marks: Sequence[BoxN], back: InkMap, source: InkMap) -> tuple[float, float]:
    raise NotImplementedError


def lies_on(marks: Sequence[BoxN], back: InkMap, source: InkMap) -> bool:
    raise NotImplementedError
