"""Analyse a document: check every page, then judge and encode them a sheet at a time.

Everything that can be refused is refused before any page is processed (see ``build``). The
pages are then worked on a sheet at a time (two pages of a duplex document, one otherwise: a hole
through the paper is told from a mark by the sheet's other side). Of each page the draft keeps
the verdict, the trim box and, for a page that stays, its encoded bytes. With ``keep_blank`` no
page is judged (the judging is the longest part of the work, and every page stays). The pixels
are gone when the sheet is done, so a document never holds more than a sheet decoded. A cancel is
honoured before each page, in the checks as well as in the processing.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from fastfoto_linux.documents.assess import PageAssessment, assess_page
from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis, TrimBox
from fastfoto_linux.documents.encode import EncodedPage, encode_page
from fastfoto_linux.documents.errors import DocumentError, stop_if_cancelled
from fastfoto_linux.documents.inkmap import ink_map
from fastfoto_linux.documents.loader import inspect_page, load_page
from fastfoto_linux.documents.neighbours import with_neighbour_flags
from fastfoto_linux.documents.settings import DocumentSettings, check_settings
from fastfoto_linux.documents.trim import Trimmed, trim_page

logger = logging.getLogger(__name__)

SIDES_PER_SHEET = 2


def _load_sheet(
    pages: Sequence[Path],
    numbers: range,
    settings: DocumentSettings,
    cancel: threading.Event | None,
) -> list[Trimmed]:
    """Load and trim the pages with these (1-based) ``numbers``: a sheet, or one page. A cancel
    is honoured before each page is decoded."""
    sheet: list[Trimmed] = []
    for number in numbers:
        stop_if_cancelled(cancel, f"page {number} of {len(pages)} was read")
        sheet.append(trim_page(load_page(pages[number - 1], fallback_dpi=settings.fallback_dpi)))
    return sheet


def _analysis(  # noqa: PLR0913 - the fields of one page
    path: Path,
    number: int,
    trimmed: Trimmed,
    *,
    partner: int | None,
    blank: bool,
    assessment: PageAssessment | None,
    encoded: EncodedPage | None,
) -> PageAnalysis:
    info = path.stat()
    return PageAnalysis(
        number=number,
        name=path.name,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        dpi=trimmed.page.dpi,
        trim=TrimBox.from_trimmed(trimmed),
        blank=blank,
        partner=partner,
        flags=frozenset() if assessment is None else assessment.flags,
        marks=() if assessment is None else assessment.marks,
        ink=None if assessment is None else ink_map(trimmed),
        encoded=encoded,
    )


def _analyse_sheet(  # noqa: PLR0913 - what a sheet needs, and the hooks, in one place
    pages: Sequence[Path],
    numbers: range,
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None,
    on_page: Callable[[int, int], None] | None,
    encode: bool,
) -> list[PageAnalysis]:
    """Judge the pages of one sheet and encode the ones that stay in the PDF.

    The sheet's pages are loaded together, because each is judged beside the other, but
    ``on_page`` and the cancel check go page by page: each comes just before its page is judged
    and encoded, so a page's progress is not reported before the page before it is encoded.
    The sheet's pixels are gone when this returns, so a document never holds more than a sheet."""
    sheet = _load_sheet(pages, numbers, settings, cancel)
    analysed: list[PageAnalysis] = []
    for index, (number, trimmed) in enumerate(zip(numbers, sheet, strict=True)):
        stop_if_cancelled(cancel, f"page {number} of {len(pages)} was processed")
        if on_page is not None:
            on_page(number, len(pages))
        paired = len(sheet) > 1
        assessment = (
            None
            if settings.keep_blank
            else assess_page(trimmed, sheet[1 - index] if paired else None)
        )
        blank = assessment is not None and assessment.verdict.blank
        partner = numbers[1 - index] if paired else None
        if blank:
            logger.info("page %d (%s) is blank and left out", number, pages[number - 1].name)
        encoded = encode_page(trimmed.page, settings.colour) if encode and not blank else None
        analysed.append(
            _analysis(
                pages[number - 1],
                number,
                trimmed,
                partner=partner,
                blank=blank,
                assessment=assessment,
                encoded=encoded,
            )
        )
    return analysed


def _common_folder(pages: Sequence[Path]) -> Path | None:
    folders = {page.parent for page in pages}
    return folders.pop() if len(folders) == 1 else None


def analyse_document(
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    on_page: Callable[[int, int], None] | None = None,
    encode: bool = True,
) -> DocumentDraft:
    """Check every page file, then judge each page and keep the verdicts in a draft.

    The settings are refused first (``check_settings``) and so is any page file that is unusable
    (a full decode, so a truncated PNG is found now); nothing is processed in either case. With
    ``encode`` the pages that stay are encoded while their sheet is decoded and the draft carries
    the bytes; without it the writer reads the raw pages again. A document of blank pages is not
    an error here: the draft says so, and the writer refuses it.

    ``on_page(number, total)`` is called before each page is judged, a blank one included, on
    the calling thread. When ``cancel`` is set DocumentCancelledError is raised.
    """
    if not pages:
        raise DocumentError("no pages to process")
    check_settings(settings)
    for number, path in enumerate(pages, start=1):
        stop_if_cancelled(cancel, f"page {number} of {len(pages)} was checked")
        inspect_page(path, fallback_dpi=settings.fallback_dpi, decode=True)
    analysed: list[PageAnalysis] = []
    step = SIDES_PER_SHEET if settings.duplex else 1
    for first in range(1, len(pages) + 1, step):
        numbers = range(first, min(first + step, len(pages) + 1))
        analysed.extend(
            _analyse_sheet(pages, numbers, settings, cancel=cancel, on_page=on_page, encode=encode)
        )
    return DocumentDraft(
        pages=tuple(with_neighbour_flags(analysed)),
        raw_dir=_common_folder(pages),
        duplex=settings.duplex,
        keep_blank=settings.keep_blank,
    )
