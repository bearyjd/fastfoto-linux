"""What ``ffscan doc`` tells the user when the PDF has been made."""

import sys

from fastfoto_linux.documents import DocumentResult, OcrStatus


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


def print_document_summary(result: DocumentResult, *, install_hint: str) -> None:
    """Counts and the file on stdout; an OCR problem on stderr."""
    dropped = f" ({_pages(result.dropped)})" if result.dropped else ""
    print(f"pages read: {result.pages_read}")
    print(f"blank pages dropped: {len(result.dropped)}{dropped}")
    print(f"pages in the PDF: {result.pages_in_pdf}")
    print(_searchable_line(result, install_hint))
    print(f"file written: {result.pdf}")
    print("raw pages: left as they were")
    if not result.ok:
        print(
            f"warning: searchable text could not be added ({result.ocr.detail}); "
            "the plain PDF was written instead",
            file=sys.stderr,
        )
