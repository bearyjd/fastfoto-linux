"""What ``ffscan doc`` tells the user when the PDF has been made."""

import sys

from fastfoto_linux.documents import DocumentResult, OcrStatus
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult

RAW_UNTOUCHED = "raw pages: left as they were"
RAW_DELETED = "raw pages: deleted (--keep-raw keeps them)"
PAGES_READ = "pages read"
PAGES_SCANNED = "pages scanned"

_KEPT_BECAUSE = {
    DocumentRawReason.CANCELLED: "the run was stopped",
    DocumentRawReason.SCAN_ERROR: "the scanner reported an error",
    DocumentRawReason.ERROR: "something went wrong",
    DocumentRawReason.OCR_FAILED: "searchable text could not be added",
    DocumentRawReason.REQUESTED: "you asked for them",
    DocumentRawReason.PAGES_DROPPED: (
        "a page was dropped as blank; --discard-raw deletes them after a clean run"
    ),
    DocumentRawReason.NOT_DELETED: "they could not be deleted",
}


def _pages(numbers: tuple[int, ...]) -> str:
    return ("page " if len(numbers) == 1 else "pages ") + ", ".join(map(str, numbers))


def _searchable_line(result: DocumentResult, install_hint: str) -> str:
    status = result.ocr.status
    if status is OcrStatus.DONE:
        return "searchable text: yes"
    if status is OcrStatus.SKIPPED:
        return "searchable text: no (off)"
    if status is OcrStatus.UNAVAILABLE:
        return f"searchable text: no (ocrmypdf is not installed; to add it: {install_hint})"
    return f"searchable text: no ({status.value})"


def raw_pages_line(session: DocumentSessionResult) -> str:
    """Where the raw pages of a scan are now, and why they are there."""
    if session.raw_dir is None or session.raw_reason is None:
        return RAW_DELETED
    return f"raw pages: kept in {session.raw_dir} ({_KEPT_BECAUSE[session.raw_reason]})"


def print_document_summary(
    result: DocumentResult,
    *,
    install_hint: str,
    pages_label: str = PAGES_READ,
    raw_line: str = RAW_UNTOUCHED,
) -> None:
    """Counts and the file on stdout; an OCR problem on stderr."""
    dropped = f" ({_pages(result.dropped)})" if result.dropped else ""
    print(f"{pages_label}: {result.pages_read}")
    print(f"blank pages dropped: {len(result.dropped)}{dropped}")
    print(f"pages in the PDF: {result.pages_in_pdf}")
    print(_searchable_line(result, install_hint))
    print(f"file written: {result.pdf}")
    print(raw_line)
    if not result.ok:
        print(
            f"warning: searchable text could not be added ({result.ocr.detail}); "
            "the plain PDF was written instead",
            file=sys.stderr,
        )
