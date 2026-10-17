"""Turn page files into one PDF: load, trim, drop blanks, encode, assemble, OCR, publish.

Order of work, and why:

1. Everything that can be refused is refused before any page is processed: the settings
   (``check_settings``: the name, the languages, a required ``ocrmypdf`` that is missing, which
   a scan session checks too before it scans) and every page file (header and a full decode, so
   a truncated PNG is found now and not after ten pages of work). Nothing is written when a
   page is unusable, because a PDF with a page silently missing is worse than no PDF.
2. Pages are then processed a sheet at a time (two pages of a duplex document, one otherwise: a
   hole through the paper is told from a mark by the sheet's other side) and only their encoded
   bytes are kept; a cancel is honoured before each page, in the checks as well as in the
   processing.
3. The OCR runs on the finished plain PDF *before* the output folder is locked (it can take
   minutes; the lock is for numbering and writing only), and a failed or timed-out OCR falls
   back to publishing the plain PDF.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from fastfoto_linux.documents.blank import is_blank_beside
from fastfoto_linux.documents.encode import EncodedPage, encode_page
from fastfoto_linux.documents.errors import (
    AllPagesBlankError,
    DocumentCancelledError,
    DocumentError,
    DocumentSettingsError,
    OcrMissingError,
)
from fastfoto_linux.documents.loader import inspect_page, load_page
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.ocr import (
    DEFAULT_LANGS,
    OcrMode,
    OcrOutcome,
    OcrStatus,
    find_ocrmypdf,
    run_ocr,
    validate_langs,
)
from fastfoto_linux.documents.pdf import assemble_pdf
from fastfoto_linux.documents.publish import publish_pdf, require_output_folder
from fastfoto_linux.documents.trim import Trimmed, trim_page
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix

logger = logging.getLogger(__name__)

DEFAULT_NAME = "Document"
OCR_BASE_S = 120.0  # the OCR time limit: this plus ...
OCR_PER_PAGE_S = 60.0  # ... this for every page
SIDES_PER_SHEET = 2


@dataclass(frozen=True)
class DocumentSettings:
    output_root: Path
    name: str = DEFAULT_NAME
    colour: ColourMode = ColourMode.COLOUR
    keep_blank: bool = False
    ocr: OcrMode = OcrMode.AUTO
    langs: str = DEFAULT_LANGS
    fallback_dpi: int | None = None
    ocr_timeout_s: float | None = None  # None: a limit that grows with the page count
    duplex: bool = True  # pages are sheets' sides in order, (1, 2), (3, 4) ...; False: all fronts


@dataclass(frozen=True)
class DocumentResult:
    pdf: Path
    pages_read: int
    dropped: tuple[int, ...]  # 1-based numbers of the pages left out as blank
    pages_in_pdf: int
    ocr: OcrOutcome

    @property
    def ok(self) -> bool:
        return self.ocr.status not in (OcrStatus.FAILED, OcrStatus.TIMED_OUT)


@dataclass(frozen=True)
class CheckedSettings:
    """What ``check_settings`` found out: the file name stem and the OCR tool to run, if any."""

    name: str
    ocr_executable: str | None


def check_settings(settings: DocumentSettings) -> CheckedSettings:
    """Refuse settings that cannot make a PDF, before any page is scanned or read.

    Raises DocumentSettingsError for a name with no usable characters or OCR languages that are
    no Tesseract codes (even with OCR off), and OcrMissingError when searchable text is required
    (``OcrMode.ON``) and ``ocrmypdf`` is not installed, and ``OutputFolderMissingError`` (a
    DocumentSettingsError) when the output folder is not an existing folder: the caller makes it,
    and a PDF is not worked on, nor a stack of paper scanned, for a folder that is not there.
    """
    try:
        name = sanitise_prefix(settings.name)
    except InvalidPrefixError as error:
        raise DocumentSettingsError(
            f"the name {settings.name!r} has no usable characters for a file name"
        ) from error
    try:
        validate_langs(settings.langs)
    except ValueError as error:
        raise DocumentSettingsError(str(error)) from error
    executable = _ocr_executable(settings.ocr)
    require_output_folder(settings.output_root)
    return CheckedSettings(name, executable)


def _now() -> datetime:
    return datetime.now().astimezone()


def _ocr_executable(mode: OcrMode) -> str | None:
    """The tool to run, or None when OCR is off or (``auto``) not installed."""
    if mode is OcrMode.OFF:
        return None
    found = find_ocrmypdf()
    if found is None and mode is OcrMode.ON:
        raise OcrMissingError("searchable text needs ocrmypdf, which is not installed")
    return found


def _stop_if_cancelled(cancel: threading.Event | None, before: str) -> None:
    if cancel is not None and cancel.is_set():
        raise DocumentCancelledError(f"stopped before {before}")


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
        _stop_if_cancelled(cancel, f"page {number} of {len(pages)} was read")
        sheet.append(trim_page(load_page(pages[number - 1], fallback_dpi=settings.fallback_dpi)))
    return sheet


def _encode_sheet(
    pages: Sequence[Path],
    numbers: range,
    settings: DocumentSettings,
    cancel: threading.Event | None,
    on_page: Callable[[int, int], None] | None,
) -> tuple[list[EncodedPage], list[int]]:
    """Encode the pages of one sheet that stay in the PDF, and number the ones dropped as blank.

    The sheet's pages are loaded together, because each is judged beside the other, but
    ``on_page`` and the cancel check go page by page: each comes just before its page is judged
    and encoded, so a page's progress is not reported before the page before it is encoded.
    The sheet's pixels are gone when this returns, so a document never holds more than a sheet."""
    sheet = _load_sheet(pages, numbers, settings, cancel)
    kept: list[EncodedPage] = []
    dropped: list[int] = []
    for index, (number, trimmed) in enumerate(zip(numbers, sheet, strict=True)):
        _stop_if_cancelled(cancel, f"page {number} of {len(pages)} was processed")
        if on_page is not None:
            on_page(number, len(pages))
        partner = sheet[1 - index] if len(sheet) > 1 else None
        if not settings.keep_blank and is_blank_beside(trimmed, partner):
            logger.info("page %d (%s) is blank and left out", number, pages[number - 1].name)
            dropped.append(number)
        else:
            kept.append(encode_page(trimmed.page, settings.colour))
    return kept, dropped


def _encode_pages(
    pages: Sequence[Path],
    settings: DocumentSettings,
    cancel: threading.Event | None,
    on_page: Callable[[int, int], None] | None,
) -> tuple[list[EncodedPage], tuple[int, ...]]:
    """Encode the pages that stay in the PDF, and number the ones dropped as blank.

    A duplex document is worked on a sheet at a time (two pages, so at most two are in memory),
    because a hole through the paper is told from a mark by the sheet's other side. An odd last
    page has no other side.
    """
    kept: list[EncodedPage] = []
    dropped: list[int] = []
    step = SIDES_PER_SHEET if settings.duplex else 1
    for first in range(1, len(pages) + 1, step):
        numbers = range(first, min(first + step, len(pages) + 1))
        sheet_kept, sheet_dropped = _encode_sheet(pages, numbers, settings, cancel, on_page)
        kept.extend(sheet_kept)
        dropped.extend(sheet_dropped)
    return kept, tuple(dropped)


def _searchable(  # noqa: PLR0913 - what OCR needs, and the one hook, in one place
    plain: bytes,
    executable: str | None,
    settings: DocumentSettings,
    page_count: int,
    *,
    cancel: threading.Event | None,
    on_ocr: Callable[[], None] | None,
) -> OcrOutcome:
    if settings.ocr is OcrMode.OFF:
        return OcrOutcome(OcrStatus.SKIPPED)
    if executable is None:
        return OcrOutcome(OcrStatus.UNAVAILABLE, "ocrmypdf is not installed")
    if on_ocr is not None:
        on_ocr()
    timeout = settings.ocr_timeout_s
    if timeout is None:
        timeout = OCR_BASE_S + OCR_PER_PAGE_S * page_count
    outcome = run_ocr(
        plain,
        executable=executable,
        langs=settings.langs,
        page_count=page_count,
        timeout_s=timeout,
        cancel=cancel,
    )
    if outcome.status is not OcrStatus.DONE:
        # The caller says so once (the CLI prints a warning); a log line would repeat it.
        logger.debug("searchable text was not added: %s", outcome.detail)
    return outcome


def build_document(  # noqa: PLR0913 - the hooks are the interface
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], datetime] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_ocr: Callable[[], None] | None = None,
) -> DocumentResult:
    """Make one PDF in ``settings.output_root`` from page files, in the order given.

    Every page file is checked first (nothing is written if one is unusable), then the pages
    are processed a sheet at a time so only encoded bytes are kept. With ``settings.duplex`` the
    pages are the two sides of sheets in order, (1, 2), (3, 4) ..., and a mark on a page that is
    a hole through the paper, also on its sheet's other side, is not a mark (see ``holes``).
    Input files are never touched.
    A failed or timed-out OCR still publishes the plain PDF (``result.ok`` is then False).
    When ``cancel`` is set DocumentCancelledError (OcrCancelledError during OCR) is raised and
    nothing is published. Settings that cannot make a PDF are refused first (``check_settings``).

    ``on_page(number, total)`` is called before each page is processed (a page that is then dropped
    as blank included) and ``on_ocr()`` once before the searchable text is made, so that a front
    end can say where the work is. Both run on the calling thread.
    """
    if not pages:
        raise DocumentError("no pages to process")
    checked = check_settings(settings)
    name, executable = checked.name, checked.ocr_executable
    for number, path in enumerate(pages, start=1):
        _stop_if_cancelled(cancel, f"page {number} of {len(pages)} was checked")
        inspect_page(path, fallback_dpi=settings.fallback_dpi, decode=True)
    encoded, dropped = _encode_pages(pages, settings, cancel, on_page)
    if not encoded:
        raise AllPagesBlankError(f"all {len(pages)} pages look blank, so no PDF was written")
    plain = assemble_pdf(encoded, title=name, created=(clock or _now)())
    outcome = _searchable(plain, executable, settings, len(encoded), cancel=cancel, on_ocr=on_ocr)
    published = publish_pdf(
        outcome.pdf if outcome.pdf is not None else plain, settings.output_root, name
    )
    # The searchable bytes are published; the result only needs to say how OCR went.
    return DocumentResult(published, len(pages), dropped, len(encoded), replace(outcome, pdf=None))
