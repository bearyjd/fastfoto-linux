"""What differs between Photos and Documents on the scan page: each mode's rules and words.

The controller owns the state both modes share (the page's state, the folder, the banner, the
scanner) and asks the mode's side for the rest. A side is what the page needs to know about one
mode; the Documents side is in ``docside``.
"""

from dataclasses import dataclass, replace
from typing import Protocol

from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.documents import DocumentItem
from fastfoto_linux.gui.form import ScanForm, destination
from fastfoto_linux.gui.photos import PhotoItem
from fastfoto_linux.gui.report import (
    Banner,
    error_banner,
    kept_text,
    progress_text,
    result_banner,
)
from fastfoto_linux.gui.state import Mode, State
from fastfoto_linux.session import DocumentSessionResult, SessionResult

CLOSE_SCAN_TITLE = "Cancel the scan?"
CLOSE_SCAN_TEXT = (
    "A scan is running. The pages scanned so far are kept so you can process them later."
)
CLOSE_PROCESSING_TITLE = "Cancel processing?"
CLOSE_PROCESSING_TEXT = (
    "Processing is running. The photos already saved stay saved, "
    "and the scanned pages are kept so you can process them later."
)


@dataclass(frozen=True)
class View:
    """What the results area shows for one mode, kept while the other mode is on the page."""

    pages: int = 0
    photos: tuple[PhotoItem, ...] = ()
    documents: tuple[DocumentItem, ...] = ()
    banner: Banner | None = None
    result: SessionResult | DocumentSessionResult | None = None
    scan_folder: str | None = None


class WorkerPort(Protocol):
    """What the controller asks of the worker."""

    def check(self) -> None: ...
    def scan(self, form: ScanForm, *, checked: bool = False) -> None: ...
    def scan_documents(
        self,
        form: DocumentForm,
        folder: str,
        *,
        ocr_available: bool,
        checked: bool = False,
        review: bool = False,
    ) -> None: ...
    def process_kept(self, kept: SessionResult | DocumentSessionResult) -> None: ...
    def cancel(self) -> None: ...


class ModeSide[R](Protocol):
    """One mode of the scan page; ``R`` is the result of its sessions."""

    def errors(self, shared: dict[str, str]) -> dict[str, str]: ...
    def destination(self, form: ScanForm) -> str | None: ...
    def progress_text(self, state: State, pages: int, photos: int, *, checking: bool) -> str: ...
    def begin_scan(self, worker: WorkerPort, form: ScanForm) -> None: ...
    def close_title(self, state: State) -> str: ...
    def close_text(self, state: State) -> str: ...
    def result_banner(self, final: State, result: R) -> Banner | None: ...
    def error_banner(self, error: BaseException, kept: R | None) -> Banner: ...
    def offers_kept(self, result: R) -> bool: ...
    def kept_text(self, result: R) -> str: ...
    def kept_after_process(self, kept: R) -> R: ...


class PhotosSide:
    """Photos mode. It keeps no state: the photos are the controller's, with the form."""

    mode = Mode.PHOTOS

    def errors(self, shared: dict[str, str]) -> dict[str, str]:
        return shared

    def destination(self, form: ScanForm) -> str | None:
        return destination(form)

    def progress_text(self, state: State, pages: int, photos: int, *, checking: bool) -> str:
        return progress_text(state, pages, photos, checking=checking)

    def begin_scan(self, worker: WorkerPort, form: ScanForm) -> None:
        worker.scan(form, checked=True)

    def close_title(self, state: State) -> str:
        return CLOSE_PROCESSING_TITLE if state is State.PROCESSING else CLOSE_SCAN_TITLE

    def close_text(self, state: State) -> str:
        return CLOSE_PROCESSING_TEXT if state is State.PROCESSING else CLOSE_SCAN_TEXT

    def result_banner(self, final: State, result: SessionResult) -> Banner | None:
        return result_banner(final, result)

    def error_banner(self, error: BaseException, kept: SessionResult | None) -> Banner:
        if kept is None:
            return error_banner(error)
        return error_banner(error, kept.raw_dir, kept.raw_reason)

    def offers_kept(self, result: SessionResult) -> bool:
        """True for a cancelled scan whose raw pages are waiting."""
        return (
            result.cancelled
            and result.error is None
            and result.process is None
            and bool(result.kept_pages)
        )

    def kept_text(self, result: SessionResult) -> str:
        return kept_text(result)

    def kept_after_process(self, kept: SessionResult) -> SessionResult:
        """Offered once: if processing fails part-way some photos are written, and a second go
        would write them again. The folder is still known for the error message."""
        return replace(kept, kept_pages=())
