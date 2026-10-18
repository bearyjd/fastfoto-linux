"""Write a document: assemble the PDF from an analysed draft, add searchable text, publish.

The pages that stay are put in one PDF as the draft holds them: a page that carries its encoded
bytes is used as it is, any other is read again from the raw pages, cut with its trim box and
encoded, one decoded page at a time. The OCR runs on the finished plain PDF *before* the output
folder is locked (it can take minutes; the lock is for numbering and writing only), and a failed
or timed-out OCR falls back to publishing the plain PDF. A cancel at any point, up to the
publishing, publishes nothing.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from fastfoto_linux.documents.draft import DocumentDraft, OutputPart, PageAnalysis
from fastfoto_linux.documents.encode import EncodedPage, encode_page
from fastfoto_linux.documents.errors import AllPagesBlankError, DocumentError, stop_if_cancelled
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.ocr import OcrMode, OcrOutcome, OcrStatus, run_ocr
from fastfoto_linux.documents.ocr_tools import ocr_missing_text
from fastfoto_linux.documents.pdf import assemble_pdf
from fastfoto_linux.documents.publish import publish_pdf
from fastfoto_linux.documents.settings import DocumentSettings, check_settings

logger = logging.getLogger(__name__)

OCR_BASE_S = 120.0  # the OCR time limit: this plus ...
OCR_PER_PAGE_S = 60.0  # ... this for every page
PART_NAME_TEMPLATE = "{name} (part {number})"  # the name of a part nobody named, among several


@dataclass(frozen=True)
class PartResult:
    """One PDF made: its file, its name (also its title), its pages and how its OCR went."""

    pdf: Path
    name: str
    pages: int
    ocr: OcrOutcome


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


def _now() -> datetime:
    return datetime.now().astimezone()


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
        return OcrOutcome(OcrStatus.UNAVAILABLE, ocr_missing_text())
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


def _encoded(
    page: PageAnalysis,
    draft: DocumentDraft,
    settings: DocumentSettings,
    cancel: threading.Event | None,
    on_page: Callable[[int, int], None] | None,
) -> EncodedPage:
    """The page as it goes into the PDF: the bytes it carries, or the raw page read again, cut
    and encoded (one decoded page at a time; a cancel is honoured before each such page)."""
    if page.encoded is not None:
        return page.encoded
    raw_dir = draft.raw_dir
    if raw_dir is None:
        raise DocumentError(
            f"page {page.number} ({page.name}) has no encoded bytes, and the draft has no "
            "folder of raw pages to read it from"
        )
    total = len(draft.pages)
    stop_if_cancelled(cancel, f"page {page.number} of {total} was written")
    if on_page is not None:
        on_page(page.number, total)
    loaded = load_page(raw_dir / page.name, fallback_dpi=settings.fallback_dpi)
    return encode_page(page.trim.apply(loaded), settings.colour)


def write_document(  # noqa: PLR0913 - the hooks are the interface
    draft: DocumentDraft,
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], datetime] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_ocr: Callable[[], None] | None = None,
) -> DocumentResult:
    """Make one PDF in ``settings.output_root`` from the pages of ``draft`` that stay.

    The settings are checked again (the folder may be gone by now). Raises AllPagesBlankError
    when no page stays. A failed or timed-out OCR still publishes the plain PDF (``result.ok``
    is then False). When ``cancel`` is set DocumentCancelledError (OcrCancelledError during OCR)
    is raised and nothing is published.

    ``on_page(number, total)`` is called before each page that is read again from the raw pages
    (a page that carries its bytes needs no work) and ``on_ocr()`` once before the searchable
    text is made. Both run on the calling thread.
    """
    checked = check_settings(settings)
    part = OutputPart(tuple((page, 0) for page in draft.kept))
    if not part.pages:
        raise AllPagesBlankError(f"all {len(draft.pages)} pages look blank, so no PDF was written")
    encoded = [_encoded(page, draft, settings, cancel, on_page) for page, _ in part.pages]
    plain = assemble_pdf(encoded, title=checked.name, created=(clock or _now)())
    outcome = _searchable(
        plain, checked.ocr_executable, settings, len(encoded), cancel=cancel, on_ocr=on_ocr
    )
    stop_if_cancelled(cancel, "the PDF was published")
    published = publish_pdf(
        outcome.pdf if outcome.pdf is not None else plain, settings.output_root, checked.name
    )
    # The searchable bytes are published; the result only needs to say how OCR went.
    return DocumentResult(
        published, len(draft.pages), draft.dropped, len(encoded), replace(outcome, pdf=None)
    )
