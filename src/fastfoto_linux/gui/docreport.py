"""The words of Documents mode: progress, results, failures, the offer to process kept pages."""

import errno
import re
from pathlib import Path
from types import MappingProxyType

from fastfoto_linux.documents import (
    DocumentError,
    DocumentResult,
    DocumentSettingsError,
    OcrMissingError,
    OcrStatus,
)
from fastfoto_linux.documents.errors import OutputFolderMissingError
from fastfoto_linux.documents.ocr_tools import OCR_UNAVAILABLE_TEXT
from fastfoto_linux.gui.documents import DocumentItem, items_from_document
from fastfoto_linux.gui.report import (
    CHECKING_SCANNER_TEXT,
    Banner,
    count_noun,
    error_text,
    sentence,
)
from fastfoto_linux.gui.state import State
from fastfoto_linux.scanner import NoDocumentsError, ScannerError
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult

_RAW_REASONS = {
    DocumentRawReason.CANCELLED: "the scan was cancelled",
    DocumentRawReason.SCAN_ERROR: "the scanner reported an error",
    DocumentRawReason.ERROR: "something went wrong",
    DocumentRawReason.OCR_FAILED: "searchable text could not be added",
    DocumentRawReason.REQUESTED: "you asked to keep them",
    DocumentRawReason.PAGES_DROPPED: "blank pages were left out",
    DocumentRawReason.NOT_DELETED: "they could not be deleted",
    DocumentRawReason.REVIEW: "they wait for your review",
}
_PLAIN_WORD = re.compile(r"[a-z]+(?=\s|$)")  # not "page-1.png:", "scan.png" or "page:"
_TOOL_NAMES = frozenset({"ocrmypdf", "tesseract", "scanimage"})
_NOT_STARTED = (DocumentSettingsError, OcrMissingError)  # refused before anything was scanned
_DISK_FULL = "The disk is full"
_NOT_ALLOWED = "The folder cannot be written to (permission denied)"
_READ_ONLY = "The folder is read-only"
_FIXABLE_OS_ERRORS = MappingProxyType(
    {
        errno.ENOSPC: _DISK_FULL,
        errno.EDQUOT: _DISK_FULL,
        errno.EACCES: _NOT_ALLOWED,
        errno.EPERM: _NOT_ALLOWED,
        errno.EROFS: _READ_ONLY,
    }
)
"""The ``OSError`` numbers a user can do something about, and what to tell them."""
EMPTY_FEEDER_TEXT = "The feeder is empty. Load the pages in the feeder and press Scan"


def document_progress_text(  # noqa: PLR0913 - the facts of one progress line are the interface
    state: State,
    pages: int,
    *,
    pdf_page: int = 0,
    pdf_total: int = 0,
    ocr: bool = False,
    checking: bool = False,
) -> str:
    """ "Scanning page N" / "Making the PDF (page N of M)" and so on while busy, else empty.

    ``checking``: the scanner is being checked before the scan starts (only while SCANNING);
    ``pdf_page`` and ``pdf_total`` are the PDF's progress, ``ocr`` that the searchable text is
    being added.
    """
    if state is State.PROCESSING:
        if ocr:
            return "Adding searchable text…"
        return (
            f"Making the PDF (page {pdf_page} of {pdf_total})" if pdf_total else "Making the PDF…"
        )
    scanning = CHECKING_SCANNER_TEXT if checking else f"Scanning page {pages + 1}"
    return {
        State.CHECKING: "Looking for the scanner…",
        State.SCANNING: scanning,
        State.CANCELLING: "Cancelling…",
    }.get(state, "")


def os_error_words(error: OSError) -> str:
    """What an ``OSError`` that stopped a PDF from being saved says, without any file name.

    The name is a temporary file the user never saw; only the kind of trouble is worth saying.
    """
    known = _FIXABLE_OS_ERRORS.get(error.errno)
    if known is not None:
        return known
    return error.strerror or "An unexpected error stopped it"


def _raw_note(raw_dir: Path | None, reason: DocumentRawReason | None) -> str:
    if raw_dir is None:
        return ""
    because = f" ({_RAW_REASONS[reason]})" if reason is not None else ""
    return f" Raw pages kept in {raw_dir}{because}."


def _capitalised(words: str) -> str:
    """``words`` starting a sentence: a plain lower-case first word gets its capital.

    A file name ("page-0002.png: ..."), a tool name ("ocrmypdf ...") or a quote stays as it is.
    """
    first = _PLAIN_WORD.match(words)
    if first is None or first.group() in _TOOL_NAMES:
        return words
    return words[:1].upper() + words[1:]


def document_error_banner(
    error: BaseException,
    raw_dir: Path | None = None,
    reason: DocumentRawReason | None = None,
) -> Banner:
    """The error banner: what went wrong, and where the raw pages are and why.

    "The scan did not start" is only for a refusal before anything was scanned (no raw pages);
    once pages are kept, a refusal or a PDF that could not be saved is "No PDF was made".
    """
    note = _raw_note(raw_dir, reason)
    if isinstance(error, _NOT_STARTED) and raw_dir is None:
        return Banner("error", f"The scan did not start: {sentence(str(error))}")
    if isinstance(error, DocumentError):
        return Banner("error", f"No PDF was made. {sentence(_capitalised(str(error)))}{note}")
    if isinstance(error, OSError) and raw_dir is not None:
        words = sentence(_capitalised(os_error_words(error)))
        return Banner("error", f"No PDF was made. {words}{note}")
    text = EMPTY_FEEDER_TEXT if isinstance(error, NoDocumentsError) else error_text(error)
    return Banner("error", f"The scan failed. {sentence(text)}{note}")


def _can_be_fixed(error: Exception) -> bool:
    """True when making the PDF again can work: the scanner had stopped, the tool or the folder
    is back, or room was made or the permission given."""
    if isinstance(error, ScannerError | OcrMissingError | OutputFolderMissingError):
        return True
    return isinstance(error, OSError) and error.errno in _FIXABLE_OS_ERRORS


def offers_kept(result: DocumentSessionResult) -> bool:
    """True when the pages kept are worth making a PDF of: a cancel, a scanner that stopped, or
    a problem the user can fix (a full disk, a folder that cannot be written to, a missing one).

    Not after an error that making the PDF again would repeat (every page blank, an unusable
    page).
    """
    if result.document is not None or not result.kept_pages:
        return False
    return result.cancelled or (result.error is not None and _can_be_fixed(result.error))


def document_kept_text(result: DocumentSessionResult) -> str:
    """What the offer to make a PDF of the kept pages says."""
    kept = len(result.kept_pages)
    if isinstance(result.error, ScannerError):
        return (
            f"The scanner stopped after {count_noun(kept, 'page')} — kept in {result.raw_dir}. "
            "A PDF made now has only the pages scanned so far."
        )
    if result.error is not None:
        verb = "is" if kept == 1 else "are"
        pages = count_noun(kept, "page")
        return f"{pages} {verb} kept in {result.raw_dir}. Fix the problem, then make the PDF."
    verb = "was" if kept == 1 else "were"
    scanned = f"{count_noun(kept, 'page')} {verb} scanned before you cancelled"
    return f"{scanned} — kept in {result.raw_dir}"


def document_result_banner(state: State, result: DocumentSessionResult) -> Banner | None:
    """The message a finished document session needs, None when it ended with nothing to say."""
    if state is State.FAILED and result.error is not None:
        return document_error_banner(result.error, result.raw_dir, result.raw_reason)
    if state is State.CANCELLED:
        if offers_kept(result):
            return Banner("info", document_kept_text(result))
        return Banner("info", "Cancelled. Nothing was scanned.")
    if state is State.DONE and result.document is not None:
        return _saved(result.document, result)
    return None


def _saved_several(items: tuple[DocumentItem, ...], note: str) -> Banner:
    """The banner of a document made into several PDFs: each one named, with its pages."""
    names = ", ".join(f"{item.file_name} ({item.pages_text})" for item in items)
    where = f"{len(items)} PDFs saved to {items[0].folder}: {names}"
    stray = [
        item.file_name for item in items if item.ocr_warning or item.ocr is OcrStatus.UNAVAILABLE
    ]
    if stray:
        return Banner(
            "warning", f"{where}. Searchable text was not added to {', '.join(stray)}.{note}"
        )
    return Banner("positive", f"{where}.{_left_out(items[0])}{note}")


def _left_out(item: DocumentItem) -> str:
    return "".join(f" {text}." for text in (item.dropped_text, item.removed_text) if text)


def _saved(document: DocumentResult, result: DocumentSessionResult) -> Banner:
    items = items_from_document(document)
    item = items[0]
    # An error that is behind us (the PDF was made on a second try) is not a reason to name now.
    reason = None if result.raw_reason is DocumentRawReason.ERROR else result.raw_reason
    note = _raw_note(result.raw_dir, reason)
    if len(items) > 1:
        return _saved_several(items, note)
    where = f"{item.file_name} saved to {item.folder}"
    if item.ocr_warning:
        said = item.searchable_text
        warning = said[:1].lower() + said[1:]
        return Banner("warning", f"{where}, but {warning}.{note}")
    if item.ocr is OcrStatus.UNAVAILABLE:  # asked for, and the tool was gone when the PDF was made
        reason = item.ocr_detail or OCR_UNAVAILABLE_TEXT  # it names what is missing
        return Banner("warning", f"{where}, but searchable text was not added ({reason}).{note}")
    return Banner("positive", f"{where}: {item.pages_text}.{_left_out(item)}{note}")
