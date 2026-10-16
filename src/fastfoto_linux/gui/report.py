"""The words the scan page shows: progress, what went wrong, where the raw pages are."""

from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.gui.state import State
from fastfoto_linux.pipeline.issues import SheetIssue, failed_sheet_line
from fastfoto_linux.pipeline.process import ProcessResult
from fastfoto_linux.scanner import NoDocumentsError, ScannerError
from fastfoto_linux.session import RawReason, SessionResult

_RAW_REASONS = {
    RawReason.CANCELLED: "the scan was cancelled",
    RawReason.SCAN_ERROR: "the scanner reported an error",
    RawReason.ERROR: "something went wrong while processing",
    RawReason.SHEETS_FAILED: "some sheets could not be processed",
    RawReason.SHEETS_DEGRADED: "some photos were saved without their enhanced copy",
    RawReason.REQUESTED: "you asked to keep them",
    RawReason.BACK_DROPPED: "a back with no writing was left out",
    RawReason.NOT_DELETED: "they could not be deleted",
}


@dataclass(frozen=True)
class Banner:
    """A message for the top of the page; ``kind`` is error, warning, info or positive."""

    kind: str
    text: str


def raw_reason_text(reason: RawReason) -> str:
    return _RAW_REASONS[reason]


def error_text(error: BaseException) -> str:
    """One readable sentence for an exception; scanner problems say what to do."""
    if isinstance(error, NoDocumentsError):
        return "The feeder is empty. Load photos in the feeder and press Scan"
    if isinstance(error, ScannerError):
        return str(error)
    if isinstance(error, OSError) and error.strerror:
        return f"{error.strerror}: {error.filename}" if error.filename else error.strerror
    return f"{type(error).__name__}: {error}"


def progress_text(state: State, pages: int, photos: int) -> str:
    """ "Scanning page N" / "Processing photo N" while busy, empty otherwise."""
    return {
        State.CHECKING: "Looking for the scanner…",
        State.SCANNING: f"Scanning page {pages + 1}",
        State.PROCESSING: f"Processing photo {photos + 1}",
        State.CANCELLING: "Cancelling…",
    }.get(state, "")


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _raw_note(raw_dir: Path | None, reason: RawReason | None) -> str:
    if raw_dir is None:
        return ""
    because = f" ({raw_reason_text(reason)})" if reason is not None else ""
    return f" Raw pages kept in {raw_dir}{because}."


def _sentence(text: str) -> str:
    """``text`` as a sentence: with a full stop unless it already ends in punctuation."""
    return text if text.endswith((".", "!", "?")) else f"{text}."


def error_banner(
    error: BaseException,
    raw_dir: Path | None = None,
    reason: RawReason | None = None,
    *,
    process_hint: bool = False,
) -> Banner:
    """The error banner: what went wrong, and where the raw pages are and why.

    ``process_hint`` adds how to process those pages later: not offered as a button, because
    processing that failed part-way has already written some photos and would write them twice.
    """
    reason_note = _raw_note(raw_dir, reason)
    hint = (
        " To process them later, run `ffscan process --out <output folder>` on those pages."
        if process_hint
        else ""
    )
    return Banner("error", f"The scan failed. {_sentence(error_text(error))}{reason_note}{hint}")


def result_banner(state: State, result: SessionResult) -> Banner | None:
    """The message a finished session needs, None when it ended cleanly with nothing to say."""
    if state is State.FAILED and result.error is not None:
        return error_banner(
            result.error, result.raw_dir, result.raw_reason, process_hint=bool(result.kept_pages)
        )
    if state is State.CANCELLED:
        return _cancelled(result)
    if state is State.DONE and result.process is not None:
        return _done(result, result.process)
    return None


def kept_text(result: SessionResult) -> str:
    """ "N pages were scanned before you cancelled — kept in <folder>"; what the offer says."""
    kept = len(result.kept_pages)
    verb = "was" if kept == 1 else "were"
    return f"{_count(kept, 'page')} {verb} scanned before you cancelled — kept in {result.raw_dir}"


def _cancelled(result: SessionResult) -> Banner:
    if result.process is not None:
        saved = result.process.photos
        verb = "was" if saved == 1 else "were"
        text = f"Cancelled. {_count(saved, 'photo')} {verb} saved."
        if whole := _saved_whole(result.process):
            text += f" {_needs_checking(len(whole))}"
        return Banner("info", text + _raw_note(result.raw_dir, None))
    if result.kept_pages:
        return Banner("info", kept_text(result))
    return Banner("info", "Cancelled. Nothing was scanned.")


def _done(result: SessionResult, process: ProcessResult) -> Banner:
    note = _raw_note(result.raw_dir, result.raw_reason)
    if process.failed:
        return Banner("warning", _failed_text(process) + note)
    if process.degraded:
        text = f"{_count(process.photos, 'photo')} saved, {len(process.degraded)} without an"
        return Banner("warning", f"{text} enhanced copy.{note}")
    if not process.photos:
        text = "No photos were found in the pages. Check that photos were loaded in the feeder."
        return Banner("warning", text + note)
    folder = process.written[-1].directory
    return Banner("positive", f"{_count(process.photos, 'photo')} saved to {folder}.{note}")


def photos_heading(total: int, unprocessed: int) -> str:
    """The results grid's heading: the photos, and those saved whole counted apart."""
    raise NotImplementedError


def _saved_whole(process: ProcessResult) -> list[SheetIssue]:
    """The failed sheets whose whole pages were saved: photos that need checking."""
    return [issue for issue in process.failed if issue.saved is not None]


def _needs_checking(count: int) -> str:
    verb = "needs" if count == 1 else "need"
    return f"{_count(count, 'photo')} {verb} checking."


def _failed_text(process: ProcessResult) -> str:
    """The failed sheets: those lost, those saved whole (which need checking), the photos saved.

    Each sheet saved whole gets a line of its own saying which photo of the batch it was, in
    feed order, why, and the file.
    """
    whole = _saved_whole(process)
    lost = len(process.failed) - len(whole)
    parts = []
    if lost:
        parts.append(f"{_count(lost, 'sheet')} could not be processed.")
    if whole:
        parts.append(_needs_checking(len(whole)))
    if process.photos:
        parts.append(f"{_count(process.photos, 'photo')} saved.")
    lines = [_sentence(_capitalised(failed_sheet_line(i, process.sheets))) for i in whole]
    return "\n".join([" ".join(parts), *lines])


def _capitalised(text: str) -> str:
    return text[:1].upper() + text[1:]
