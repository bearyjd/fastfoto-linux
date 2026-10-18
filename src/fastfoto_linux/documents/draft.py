"""The analysed document: what is known about each page before the PDF is written.

A draft holds numbers, flags and the encoded bytes of the pages that stay, never decoded pixels,
so it is as small as a document's compressed pages. A page is named by its raw number (its place,
counting from 1, in the list the document was made from), which does not change when the files
move.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

from fastfoto_linux.documents.encode import EncodedPage
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.trim import Trimmed


@dataclass(frozen=True)
class TrimBox:
    """How a page was trimmed: the pixels cut off each side, as ``Trimmed`` reports them.

    Trimming is a pure crop, so these four numbers give the trimmed page back from the raw one
    (``apply``) without keeping a trimmed copy of it. ``band_bottom`` says the bottom cut ended
    at the paper's own edge (see ``Trimmed.tail_rows``).
    """

    left: int
    right: int
    top: int
    bottom: int
    band_bottom: bool = False

    def __post_init__(self) -> None:
        if min(self.left, self.right, self.top, self.bottom) < 0:
            raise ValueError("a trim box cannot cut a negative number of pixels")

    @classmethod
    def from_trimmed(cls, trimmed: Trimmed) -> "TrimBox":
        return cls(trimmed.left, trimmed.right, trimmed.top, trimmed.bottom, trimmed.band_bottom)

    def apply(self, page: LoadedPage) -> LoadedPage:
        """``page`` cut as the box says: the page ``trim_page`` made, given the raw page.

        The input is not modified; the result may share memory with it, as in ``trim_page``.
        Raises ValueError when the box would leave nothing of the page.
        """
        height, width = page.pixels.shape[:2]
        if self.left + self.right >= width or self.top + self.bottom >= height:
            raise ValueError(f"the trim box leaves nothing of a {width} x {height} pixel page")
        pixels = page.pixels[self.top : height - self.bottom, self.left : width - self.right]
        return replace(page, pixels=pixels)


class Flag(StrEnum):
    """Why a verdict is what it is, for a reviewer. A flag explains; it never drops or keeps a
    page. The first six come with a page that stays, the last two with a page left out."""

    FEW_MARKS = "few_marks"  # at most 3 marks, under 2 cm2 of them: a signature, a stray mark
    EDGE_ONLY = "edge_only"  # every mark lies near an edge of the page
    HOLE_LIKE = "hole_like"  # a mark that looks like a hole has no counterpart on the other side
    FAINT_ONLY = "faint_only"  # every mark is pale (pencil, a ghost)
    SHOW_THROUGH = "show_through"  # the marks are paler copies of the other side's, mirrored
    SET_OFF = "set_off"  # the marks mirror a neighbouring sheet's printed side
    CREASE_IGNORED = "crease_ignored"  # a fold crease was found on the page and ignored
    HOLES_MATCHED = "holes_matched"  # every mark is a hole the sheet's other side shows too


@dataclass(frozen=True)
class BoxN:
    """A mark's box as shares (0 to 1) of the trimmed page: where to draw it, nothing more."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class InkMap:
    """A coarse map of where a page is dark: one bit per cell (row by row, packed), the cells
    ``cell_mm`` square, from the page's top left corner. The page lies ``left_mm`` and ``top_mm``
    from the corner of the scanner's frame, which is ``frame_mm`` wide; ``width_mm`` and
    ``height_mm`` are the page's. Small (about 5 KB for Letter) and never persisted."""

    bits: bytes
    cols: int
    rows: int
    cell_mm: float
    left_mm: float
    top_mm: float
    width_mm: float
    height_mm: float
    frame_mm: float


def sorted_flags(flags: Iterable[Flag]) -> tuple[Flag, ...]:
    """The flags in a stable order (by name), to print or compare."""
    return tuple(sorted(flags))


@dataclass(frozen=True)
class PageAnalysis:
    """One page: which file it came from, how it was trimmed and whether it looks blank.

    ``blank`` is the verdict, False for every page of a document made with ``keep_blank`` (its
    pages are not judged). ``size`` and ``mtime_ns`` identify the file that was analysed.
    ``partner`` is the raw number of the sheet's other side (None: it has none). ``encoded`` is
    the page as it goes into the PDF, held in memory only and only for a page that stays; it is
    not part of the page's identity (two analyses of a page are equal whether or not they carry
    it). ``flags`` explain the verdict (see ``Flag``) and ``marks`` are the boxes of the page's
    marks, the largest 24 at most.
    """

    number: int
    name: str
    size: int
    mtime_ns: int
    dpi: int
    trim: TrimBox
    blank: bool
    partner: int | None = None
    flags: frozenset[Flag] = frozenset()
    marks: tuple[BoxN, ...] = ()
    detail: tuple[str, ...] = ()
    ink: InkMap | None = field(default=None, repr=False, compare=False)
    encoded: EncodedPage | None = field(default=None, repr=False, compare=False)

    def describe(self) -> str:
        """Numbers and flag names only, stably ordered: ``page 3 kept flags=few_marks marks=2``."""
        verdict = "blank" if self.blank else "kept"
        names = ",".join(sorted_flags(self.flags)) or "-"
        text = f"page {self.number} {verdict} flags={names} marks={len(self.marks)}"
        return text + "".join(f" {name}" for name in self.detail)


@dataclass(frozen=True)
class DocumentDraft:
    """The pages of a document in order. ``raw_dir`` is the folder that holds all the page files
    (None: they are not in one folder)."""

    pages: tuple[PageAnalysis, ...]
    raw_dir: Path | None
    duplex: bool
    keep_blank: bool

    @property
    def kept(self) -> tuple[PageAnalysis, ...]:
        """The pages that go into the PDF: all of them with ``keep_blank``, else the ones that
        do not look blank."""
        return tuple(page for page in self.pages if self.keep_blank or not page.blank)

    @property
    def dropped(self) -> tuple[int, ...]:
        """The raw numbers of the pages left out as blank."""
        return tuple(page.number for page in self.pages if page.blank and not self.keep_blank)


@dataclass(frozen=True)
class OutputPart:
    """The pages of one PDF, in order."""

    pages: tuple[PageAnalysis, ...]
