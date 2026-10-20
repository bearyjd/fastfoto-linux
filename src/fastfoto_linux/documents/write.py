"""Write a document: assemble the PDFs from an analysed draft, add searchable text, publish.

The pages that stay are put in one PDF for each part of the draft as it holds them: a page that
carries its encoded bytes (and is not turned) is used as it is, any other is read again from the
raw pages, cut with its trim box, turned and encoded, one decoded page at a time. The OCR runs
on each finished plain PDF *before* the output folder is locked (it can take minutes; the lock
is for numbering and writing only), with a limit that grows with that part's page count, and a
failed or timed-out OCR falls back to publishing the plain PDF. Every part is made before any is
published: a cancel or an error at any point up to the publishing publishes nothing.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np

from fastfoto_linux.documents.auto_colour import (
    classify_colour,
    page_colour,
    page_policy,
    resolve_colour,
)
from fastfoto_linux.documents.draft import DocumentDraft, OutputPart, PageAnalysis
from fastfoto_linux.documents.draft_edit import parts
from fastfoto_linux.documents.encode import EncodedPage, encode_page
from fastfoto_linux.documents.errors import (
    AllPagesBlankError,
    DocumentError,
    NothingSelectedError,
    stop_if_cancelled,
)
from fastfoto_linux.documents.loader import LoadedPage, load_page
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy
from fastfoto_linux.documents.ocr import OcrMode, OcrOutcome, OcrStatus, run_ocr
from fastfoto_linux.documents.ocr_tools import ocr_missing_text
from fastfoto_linux.documents.pdf import assemble_pdf
from fastfoto_linux.documents.publish import publish_pdfs
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


# From the worst outcome to the best: what the document's OCR outcome says when its parts differ.
_OCR_SEVERITY = (
    OcrStatus.FAILED,
    OcrStatus.TIMED_OUT,
    OcrStatus.UNAVAILABLE,
    OcrStatus.SKIPPED,
    OcrStatus.DONE,
)


@dataclass(frozen=True)
class DocumentResult:
    """What a run made: one ``PartResult`` per PDF. ``dropped`` are the 1-based numbers of the
    pages left out as blank, ``removed`` those the reviewer left out. ``pdf``, ``pages_in_pdf``,
    ``ocr`` and ``ok`` are the first PDF, the pages in all of them, the worst OCR outcome and
    "no part's OCR failed"."""

    pages_read: int
    dropped: tuple[int, ...]
    parts: tuple[PartResult, ...]
    removed: tuple[int, ...] = ()

    @property
    def pdf(self) -> Path:
        return self.parts[0].pdf

    @property
    def pages_in_pdf(self) -> int:
        return sum(part.pages for part in self.parts)

    @property
    def ocr(self) -> OcrOutcome:
        return min((part.ocr for part in self.parts), key=lambda o: _OCR_SEVERITY.index(o.status))

    @property
    def ok(self) -> bool:
        return all(
            part.ocr.status not in (OcrStatus.FAILED, OcrStatus.TIMED_OUT) for part in self.parts
        )


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


def _turned(page: LoadedPage, turns: int) -> LoadedPage:
    """``page`` turned ``turns`` quarter turns clockwise, exactly (no resampling)."""
    if turns == 0:
        return page
    return replace(page, pixels=np.ascontiguousarray(np.rot90(page.pixels, -turns)))


def _read_page(page: PageAnalysis, turns: int, draft: DocumentDraft) -> LoadedPage:
    """The raw page read, cut with its trim box and turned. The raw pixels are released on
    return when the page is turned, so one decoded page is held while it is encoded."""
    raw_dir = draft.raw_dir
    if raw_dir is None:
        raise DocumentError(
            f"page {page.number} ({page.name}) has no encoded bytes, and the draft has no "
            "folder of raw pages to read it from"
        )
    loaded = load_page(raw_dir / page.name, fallback_dpi=page.dpi)
    return _turned(page.trim.apply(loaded), turns)


@dataclass(frozen=True)
class _Run:
    """What making every part of one document needs."""

    draft: DocumentDraft
    settings: DocumentSettings
    executable: str | None
    cancel: threading.Event | None
    clock: Callable[[], datetime] | None
    on_page: Callable[[int, int], None] | None
    on_ocr: Callable[[], None] | None


def _encoded(run: "_Run", page: PageAnalysis, turns: int) -> EncodedPage:
    """The page as it goes into the PDF: the bytes it carries (when it is not turned), or the
    raw page read again, cut, turned and encoded (one decoded page at a time; a cancel is
    honoured before each such page)."""
    stop_if_cancelled(run.cancel, f"page {page.number} of {len(run.draft.pages)} was written")
    policy = page_policy(run.draft, page, run.settings.colour)
    kept = page.encoded if turns == 0 else None
    mode: ColourMode | None = None
    if page.colour is not None or policy is not ColourPolicy.AUTO:
        mode = page_colour(run.draft, page, run.settings.colour)
        if kept is not None and kept.mode is mode:
            return kept
    loaded = _read_page(page, turns, run.draft)
    if mode is None:  # Auto on a page that was not analysed: classify it once, here
        mode = resolve_colour(classify_colour(loaded), policy)
        if kept is not None and kept.mode is mode:
            return kept
    if run.on_page is not None:
        run.on_page(page.number, len(run.draft.pages))
    return encode_page(loaded, mode)


def _make_part(run: _Run, part: OutputPart, name: str) -> tuple[str, bytes, int, OcrOutcome]:
    """The PDF of one part, with searchable text when it can have it: its name, the bytes to
    publish, its page count and how the OCR went."""
    encoded = [_encoded(run, page, turns) for page, turns in part.pages]
    plain = assemble_pdf(encoded, title=name, created=(run.clock or _now)())
    outcome = _searchable(
        plain, run.executable, run.settings, len(encoded), cancel=run.cancel, on_ocr=run.on_ocr
    )
    return name, outcome.pdf if outcome.pdf is not None else plain, len(encoded), outcome


def _part_name(part: OutputPart, number: int, count: int, document_name: str) -> str:
    """The name the reviewer gave the part, else the document's (with the part's number when
    there are several parts)."""
    if part.name:
        return part.name
    if count == 1:
        return document_name
    return PART_NAME_TEMPLATE.format(name=document_name, number=number)


def write_document(  # noqa: PLR0913 - the hooks are the interface
    draft: DocumentDraft,
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], datetime] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_ocr: Callable[[], None] | None = None,
) -> DocumentResult:
    """Make the PDFs in ``settings.output_root`` from the pages of ``draft`` that stay: one
    PDF, or one for each part the draft's splits make (see ``draft_edit.parts``).

    The settings are checked again (the folder may be gone by now). Raises AllPagesBlankError
    when no page stays and nothing was edited, NothingSelectedError when the edits left no page.
    A failed or timed-out OCR still publishes the plain PDF (``result.ok`` is then False). Every
    part is made before any is published, so when ``cancel`` is set DocumentCancelledError
    (OcrCancelledError during OCR) is raised, or anything else fails, nothing is published.

    ``on_page(number, total)`` is called before each page that is read again from the raw pages
    (a page that carries its bytes and is not turned needs no work) and ``on_ocr()`` before the
    searchable text of each part is made. Both run on the calling thread.
    """
    checked = check_settings(settings)
    output = parts(draft)
    if not output:
        if not draft.has_edits:
            raise AllPagesBlankError(
                f"all {len(draft.pages)} pages look blank, so no PDF was written"
            )
        raise NothingSelectedError(
            f"no page is left to write: all {len(draft.pages)} pages were left out"
        )
    run = _Run(draft, settings, checked.ocr_executable, cancel, clock, on_page, on_ocr)
    made = [
        _make_part(run, part, _part_name(part, number, len(output), checked.name))
        for number, part in enumerate(output, start=1)
    ]
    stop_if_cancelled(cancel, "the PDF was published")
    published = publish_pdfs([(name, data) for name, data, _, _ in made], settings.output_root)
    # The searchable bytes are published; the result only needs to say how OCR went.
    results = tuple(
        PartResult(path, name, pages, replace(outcome, pdf=None))
        for path, (name, _, pages, outcome) in zip(published, made, strict=True)
    )
    return DocumentResult(len(draft.pages), draft.dropped, results, draft.removed)
