"""One verdict code path for a page, and the flags that explain it (stub: red commit)."""

from dataclasses import dataclass

from fastfoto_linux.documents.draft import BoxN, Flag
from fastfoto_linux.documents.holes import HoleReport
from fastfoto_linux.documents.marks import Mark
from fastfoto_linux.documents.trim import Trimmed


@dataclass(frozen=True)
class BlankVerdict:
    """Whether a page is blank, and what the verdict was made of."""

    blank: bool
    marks: tuple[Mark, ...]
    holes: HoleReport | None
    crease_ignored: bool


@dataclass(frozen=True)
class PageAssessment:
    """The verdict of a page, the flags that explain it and the boxes of its marks."""

    verdict: BlankVerdict
    flags: frozenset[Flag]
    marks: tuple[BoxN, ...]


def blank_verdict(page: Trimmed, partner: Trimmed | None) -> BlankVerdict:
    raise NotImplementedError


def assess_page(page: Trimmed, partner: Trimmed | None) -> PageAssessment:
    raise NotImplementedError
