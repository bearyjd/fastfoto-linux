"""What a scan session reports back."""

from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path

from fastfoto_linux.documents import DocumentResult
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.pipeline.process import ProcessResult


class Stage(StrEnum):
    """Where a session is, for a progress display."""

    CHECKING = auto()  # the scanner is checked (and freed if stuck) before the scan starts
    WAITING = auto()  # the check ran past a couple of seconds: the scanner is slow to answer
    SCANNING = auto()
    PROCESSING = auto()
    DONE = auto()  # the raw pages are settled and the result is about to be returned


class RawReason(StrEnum):
    """Why the raw pages are still on disk after a session (the first that applies)."""

    CANCELLED = auto()  # the scan or the processing was cancelled or interrupted
    SCAN_ERROR = auto()  # the scanner failed
    ERROR = auto()  # anything else went wrong (processing crashed, a callback raised)
    SHEETS_FAILED = auto()  # a sheet could not be processed
    SHEETS_DEGRADED = auto()  # a sheet was written without its enhanced copy
    REQUESTED = auto()  # the raw policy is KEEP
    BACK_DROPPED = auto()  # a back with no writing was dropped (policy AUTO)
    NOT_DELETED = auto()  # nothing asked for them, but they could not be deleted


@dataclass(frozen=True)
class SessionResult:
    """How a session ended.

    ``process`` is None when there is no processing result to show: the scan was cancelled or
    failed without leaving pages, or processing itself ended by an interrupt or an exception
    (an ``on_photo`` callback's, say: the photos written before it are on disk, but not
    listed). ``pages_scanned`` counts the pages the scanner delivered, 0 when the scan ended
    by an exception that did not say. ``raw_dir`` is where the raw pages are now, None when
    they were deleted (or there were none), and ``raw_reason`` says why they stay: both are
    set, or neither. ``kept_pages`` are the finished page files in ``raw_dir`` (a page cut off
    mid-write when the scan stopped stays on disk but is not listed), in page order, whether or
    not processing got to them (empty when ``raw_dir`` is None): after a cancel during the scan
    they are the pages scanned so far, none processed, which a front end can offer to process
    later. ``error`` is what stopped the session early: a scanner failure (the pages scanned
    before it were still processed), or any other exception, which is handed back and not
    raised so that the raw pages are settled first. ``cancelled`` is True after a cancel or an
    interrupt that stopped something; a cancel that came when nothing was left to stop (the
    last sheet was already being handled) leaves a complete result that is not cancelled.
    """

    process: ProcessResult | None = None
    pages_scanned: int = 0
    raw_dir: Path | None = None
    raw_reason: RawReason | None = None
    error: Exception | None = None
    cancelled: bool = False
    kept_pages: tuple[Path, ...] = ()

    @property
    def ok(self) -> bool:
        """True when everything was scanned and processed without a problem."""
        return (
            self.error is None
            and not self.cancelled
            and self.process is not None
            and self.process.ok
        )


class DocumentRawReason(StrEnum):
    """Why the raw pages are still on disk after a document session (the first that applies)."""

    CANCELLED = auto()  # the scan or the PDF was cancelled or interrupted
    SCAN_ERROR = auto()  # the scanner failed
    ERROR = auto()  # anything else went wrong (a page unusable, every page blank, a crash)
    OCR_FAILED = auto()  # the PDF was written without its searchable text
    REQUESTED = auto()  # the raw policy is KEEP
    PAGES_DROPPED = auto()  # blank pages were left out of the PDF (policy AUTO)
    NOT_DELETED = auto()  # nothing asked for them, but they could not be deleted
    REVIEW = auto()  # the pages wait for a review (they are never deleted then)


@dataclass(frozen=True)
class DocumentSessionResult:
    """How a document session ended; the fields mean what they do in :class:`SessionResult`."""

    document: DocumentResult | None = None
    pages_scanned: int = 0
    raw_dir: Path | None = None
    raw_reason: DocumentRawReason | None = None
    error: Exception | None = None
    cancelled: bool = False
    kept_pages: tuple[Path, ...] = ()
    draft: DocumentDraft | None = None

    @property
    def ok(self) -> bool:
        """True when the PDF was made without a problem (searchable text included)."""
        return (
            self.error is None
            and not self.cancelled
            and self.document is not None
            and self.document.ok
        )
