"""Turn page files into one PDF: load, trim, drop blanks, encode, assemble, OCR, publish.

Order of work, and why:

1. Everything that can be refused is refused before any page is processed: the settings
   (``check_settings``: the name, the languages, a required ``ocrmypdf`` that is missing, which
   a scan session checks too before it scans) and every page file (header and a full decode, so
   a truncated PNG is found now and not after ten pages of work). Nothing is written when a
   page is unusable, because a PDF with a page silently missing is worse than no PDF.
2. Pages are then processed one at a time and only their encoded bytes are kept; a cancel is
   honoured before each page, in the checks as well as in the processing.
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

from fastfoto_linux.documents.blank import is_blank
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
from fastfoto_linux.documents.publish import publish_pdf
from fastfoto_linux.documents.trim import trim_page
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix

logger = logging.getLogger(__name__)

DEFAULT_NAME = "Document"
OCR_BASE_S = 120.0  # the OCR time limit: this plus ...
OCR_PER_PAGE_S = 60.0  # ... this for every page


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
    (``OcrMode.ON``) and ``ocrmypdf`` is not installed. The output folder is not checked here:
    it is the caller's to make, and publishing refuses a missing one.
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
    return CheckedSettings(name, _ocr_executable(settings.ocr))


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


def _encode_pages(
    pages: Sequence[Path], settings: DocumentSettings, cancel: threading.Event | None
) -> tuple[list[EncodedPage], tuple[int, ...]]:
    """Encode the pages that stay in the PDF, and number the ones dropped as blank."""
    kept: list[EncodedPage] = []
    dropped: list[int] = []
    for number, path in enumerate(pages, start=1):
        _stop_if_cancelled(cancel, f"page {number} of {len(pages)} was processed")
        trimmed = trim_page(load_page(path, fallback_dpi=settings.fallback_dpi))
        page = trimmed.page
        if not settings.keep_blank and is_blank(page, trimmed_bottom=trimmed.tail_rows):
            logger.info("page %d (%s) is blank and left out", number, path.name)
            dropped.append(number)
            continue
        kept.append(encode_page(page, settings.colour))
    return kept, tuple(dropped)


def _searchable(
    plain: bytes,
    executable: str | None,
    settings: DocumentSettings,
    page_count: int,
    cancel: threading.Event | None,
) -> OcrOutcome:
    if settings.ocr is OcrMode.OFF:
        return OcrOutcome(OcrStatus.SKIPPED)
    if executable is None:
        return OcrOutcome(OcrStatus.UNAVAILABLE, "ocrmypdf is not installed")
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


def build_document(
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], datetime] | None = None,
) -> DocumentResult:
    """Make one PDF in ``settings.output_root`` from page files, in the order given.

    Every page file is checked first (nothing is written if one is unusable), then the pages
    are processed one at a time so only encoded bytes are kept. Input files are never touched.
    A failed or timed-out OCR still publishes the plain PDF (``result.ok`` is then False).
    When ``cancel`` is set DocumentCancelledError (OcrCancelledError during OCR) is raised and
    nothing is published. Settings that cannot make a PDF are refused first (``check_settings``).
    """
    if not pages:
        raise DocumentError("no pages to process")
    checked = check_settings(settings)
    name, executable = checked.name, checked.ocr_executable
    for number, path in enumerate(pages, start=1):
        _stop_if_cancelled(cancel, f"page {number} of {len(pages)} was checked")
        inspect_page(path, fallback_dpi=settings.fallback_dpi, decode=True)
    encoded, dropped = _encode_pages(pages, settings, cancel)
    if not encoded:
        raise AllPagesBlankError(f"all {len(pages)} pages look blank, so no PDF was written")
    plain = assemble_pdf(encoded, title=name, created=(clock or _now)())
    outcome = _searchable(plain, executable, settings, len(encoded), cancel)
    published = publish_pdf(
        outcome.pdf if outcome.pdf is not None else plain, settings.output_root, name
    )
    # The searchable bytes are published; the result only needs to say how OCR went.
    return DocumentResult(published, len(pages), dropped, len(encoded), replace(outcome, pdf=None))
