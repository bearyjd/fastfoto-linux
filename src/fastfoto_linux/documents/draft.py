"""The analysed document: what is known about each page before the PDF is written."""

from dataclasses import dataclass, field
from pathlib import Path

from fastfoto_linux.documents.encode import EncodedPage
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.trim import Trimmed


@dataclass(frozen=True)
class TrimBox:
    """How a page was trimmed: the pixels cut off each side, as ``Trimmed`` reports them."""

    left: int
    right: int
    top: int
    bottom: int
    band_bottom: bool = False

    @classmethod
    def from_trimmed(cls, trimmed: Trimmed) -> "TrimBox":
        raise NotImplementedError

    def apply(self, page: LoadedPage) -> LoadedPage:
        raise NotImplementedError


@dataclass(frozen=True)
class PageAnalysis:
    number: int
    name: str
    size: int
    mtime_ns: int
    dpi: int
    trim: TrimBox
    blank: bool
    partner: int | None = None
    encoded: EncodedPage | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class DocumentDraft:
    pages: tuple[PageAnalysis, ...]
    raw_dir: Path | None
    duplex: bool
    keep_blank: bool

    @property
    def kept(self) -> tuple[PageAnalysis, ...]:
        raise NotImplementedError

    @property
    def dropped(self) -> tuple[int, ...]:
        raise NotImplementedError


@dataclass(frozen=True)
class OutputPart:
    pages: tuple[PageAnalysis, ...]
