"""The analysed document: what is known about each page before the PDF is written.

A draft holds numbers, flags and the encoded bytes of the pages that stay, never decoded pixels,
so it is as small as a document's compressed pages. A page is named by its raw number (its place,
counting from 1, in the list the document was made from), which does not change when the files
move.
"""

from dataclasses import dataclass, field, replace
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


@dataclass(frozen=True)
class PageAnalysis:
    """One page: which file it came from, how it was trimmed and whether it looks blank.

    ``blank`` is the verdict, False for every page of a document made with ``keep_blank`` (its
    pages are not judged). ``size`` and ``mtime_ns`` identify the file that was analysed.
    ``partner`` is the raw number of the sheet's other side (None: it has none). ``encoded`` is
    the page as it goes into the PDF, held in memory only and only for a page that stays; it is
    not part of the page's identity (two analyses of a page are equal whether or not they carry
    it).
    """

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
