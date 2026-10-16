"""The logic of the scan page, free of Qt: the form, the state and what the results say.

The controller is a worker sink whose methods must be called on one thread (the GUI's). A front
end that runs the worker on another thread hands every sink call over to that thread first.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from fastfoto_linux.gui.docform import (
    FOLDER_FIELD,
    DocumentForm,
    document_destination,
    update_document_field,
    validate_document_form,
)
from fastfoto_linux.gui.docreport import (
    document_error_banner,
    document_kept_text,
    document_progress_text,
    document_result_banner,
    offers_kept,
)
from fastfoto_linux.gui.doctools import DocumentSetup
from fastfoto_linux.gui.documents import DocumentItem, item_from_document
from fastfoto_linux.gui.form import (
    FormInvalidError,
    ScanForm,
    destination,
    merge_errors,
    update_field,
    validate_filesystem,
    validate_syntax,
)
from fastfoto_linux.gui.photos import PhotoItem, item_from_files
from fastfoto_linux.gui.report import (
    Banner,
    error_banner,
    error_text,
    kept_text,
    progress_text,
    result_banner,
)
from fastfoto_linux.gui.state import (
    ActionBlockedError,
    Mode,
    State,
    can_cancel,
    final_state,
    is_busy,
    transition,
)
from fastfoto_linux.gui.worker import WorkerBusyError
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.scanner import ScannerNotFoundError, ShimMissingError
from fastfoto_linux.session import DocumentSessionResult, SessionResult, Stage

logger = logging.getLogger(__name__)

_SCANNABLE = frozenset({State.READY, State.DONE, State.FAILED, State.CANCELLED})
_RUNNING = (State.SCANNING, State.PROCESSING)
_REPORTING = frozenset({State.SCANNING, State.PROCESSING, State.CANCELLING})
_DISK_FIELDS = frozenset({"output_folder", "album"})
CHECKING_DISK_TEXT = "Checking the folder…"
PROCESS_KEPT_TEXT = "Process them now"
NOT_CHECKED = "The scanner has not been checked yet."
CHECKING_TEXT = "Looking for the scanner…"
FOUND_TEXT = "Scanner found."
NO_SCANNER_HINT = "Press Check again to look for the scanner."
LOST_TEXT = "The scanner is not available; the message above says why."
CLOSE_SCAN_TITLE = "Cancel the scan?"
CLOSE_SCAN_TEXT = (
    "A scan is running. The pages scanned so far are kept so you can process them later."
)
CLOSE_PROCESSING_TITLE = "Cancel processing?"
CLOSE_PROCESSING_TEXT = (
    "Processing is running. The photos already saved stay saved, "
    "and the scanned pages are kept so you can process them later."
)
CLOSE_PDF_TITLE = "Cancel making the PDF?"
CLOSE_PDF_TEXT = (
    "The PDF is being made. If you cancel, no PDF is saved, "
    "and the scanned pages are kept so you can make it later."
)


DiskKey = tuple[str, str]
DiskCheck = Callable[[ScanForm], None]
"""Starts reading the disk for a form and returns at once; the answer goes to ``on_disk``."""


def disk_key(form: ScanForm) -> DiskKey:
    """What a read of the disk depends on: the output folder and the album."""
    return (form.output_folder.strip(), form.album.strip())


def _lost(error: BaseException | None) -> bool:
    """True when the scanner itself is gone; a jam or an empty feeder leaves it found."""
    return isinstance(error, ScannerNotFoundError | ShimMissingError)


@dataclass(frozen=True)
class _View:
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
        self, form: DocumentForm, folder: str, *, ocr_available: bool, checked: bool = False
    ) -> None: ...
    def process_kept(self, kept: SessionResult | DocumentSessionResult) -> None: ...
    def cancel(self) -> None: ...


class Controller:
    """The scan page's state, form and results; ``on_change`` hears every change."""

    def __init__(  # noqa: PLR0913 - the collaborators are the interface
        self,
        worker: WorkerPort,
        form: ScanForm | None = None,
        *,
        save_form: Callable[[ScanForm], None] | None = None,
        on_change: Callable[[], None] | None = None,
        disk_check: DiskCheck | None = None,
        documents: DocumentSetup | None = None,
    ) -> None:
        self._worker = worker
        self._disk_check = disk_check
        self._save_form = save_form
        self._on_change = on_change
        self._state = State.IDLE
        self._scanner_ready = False
        self._scanner_message = NOT_CHECKED
        self._pages = 0
        self._photos: tuple[PhotoItem, ...] = ()
        self._banner: Banner | None = None
        self._result: SessionResult | DocumentSessionResult | None = None
        self._close_requested = False
        self._scan_folder: str | None = None
        self._disk_errors: dict[str, str] = {}
        self._disk_pending: DiskKey | None = None  # the folder check we are waiting for
        self._scan_when_checked = False  # ... and it is the one that starts a scan
        self._checking_scanner = False  # the scan is in its check of the scanner
        setup = documents or DocumentSetup()
        self._mode = setup.mode
        self._doc_form = setup.form
        self._tools = setup.tools
        self._save_doc_form = setup.save_form
        self._save_mode = setup.save_mode
        self._ocr_available, self._ocr_hint = False, ""
        self._documents: tuple[DocumentItem, ...] = ()
        self._pdf_page, self._pdf_total, self._ocr_running = 0, 0, False
        self._other_views: dict[Mode, _View] = {}
        self._look_for_ocr()
        self._set_form(form or ScanForm(), disk=disk_check is None)

    # -- what the page shows -------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def form(self) -> ScanForm:
        return self._form

    @property
    def errors(self) -> dict[str, str]:
        """A message per bad field: the text checked at every edit, the disk when it was read.

        In Documents mode the folder (shared) and the Documents fields; a photo album is no
        business of a document.
        """
        shared = merge_errors(self._syntax_errors, self._disk_errors)
        if self._mode is Mode.PHOTOS:
            return shared
        folder = {name: message for name, message in shared.items() if name == FOLDER_FIELD}
        return {**folder, **validate_document_form(self._doc_form)}

    @property
    def destination(self) -> str | None:
        if self._mode is Mode.DOCUMENTS:
            return document_destination(self._doc_form, self._form.output_folder)
        return self._destination

    @property
    def scanner_text(self) -> str:
        return CHECKING_TEXT if self._state is State.CHECKING else self._scanner_message

    @property
    def progress_text(self) -> str:
        if self._mode is Mode.DOCUMENTS:
            return document_progress_text(
                self._state,
                self._pages,
                pdf_page=self._pdf_page,
                pdf_total=self._pdf_total,
                ocr=self._ocr_running,
                checking=self._checking_scanner,
            )
        return progress_text(
            self._state, self._pages, len(self._photos), checking=self._checking_scanner
        )

    @property
    def photos(self) -> tuple[PhotoItem, ...]:
        return self._photos

    @property
    def results_folder(self) -> Path | None:
        """The folder the latest photo or PDF was written to, None before there is one."""
        if self._mode is Mode.DOCUMENTS:
            return self._documents[-1].folder if self._documents else None
        return self._photos[-1].directory if self._photos else None

    @property
    def banner(self) -> Banner | None:
        return self._banner

    @property
    def busy(self) -> bool:
        """True while a job runs, or while the folder is looked at before a scan starts."""
        return is_busy(self._state) or self.starting_scan

    @property
    def running(self) -> bool:
        """True while a scan is made, processed or cancelled: a window must not just close."""
        return self._state in (*_RUNNING, State.CANCELLING)

    @property
    def scanner_ready(self) -> bool:
        """True when the last check found the scanner and nothing since has lost it."""
        return self._scanner_ready

    @property
    def can_scan(self) -> bool:
        """True when Scan may be pressed.

        A folder check under way does not stop it: pressing Scan leaves the folder field, which
        starts that check, and the press must not be lost. The press waits for the answer.
        """
        return (
            self._state in _SCANNABLE
            and self._scanner_ready
            and not self.errors
            and not self.starting_scan
        )

    @property
    def scan_blocker(self) -> str:
        """Why Scan is disabled, in words for the user; empty when it is enabled or a job runs."""
        if self.starting_scan:
            return CHECKING_DISK_TEXT
        if self.busy or self.can_scan:
            return ""
        errors = self.errors
        if errors:
            return next(iter(errors.values()))
        return "" if self._scanner_ready else NO_SCANNER_HINT

    @property
    def can_cancel(self) -> bool:
        return can_cancel(self._state)

    @property
    def starting_scan(self) -> bool:
        """True while the folder is looked at before the scan starts (``cancel`` gives it up)."""
        return self._scan_when_checked

    @property
    def can_check(self) -> bool:
        return not self.busy

    @property
    def can_process_kept(self) -> bool:
        """True while the last result is a cancelled scan whose raw pages are waiting."""
        result = self._result
        if isinstance(result, DocumentSessionResult):
            return not self.busy and offers_kept(result)
        return (
            not self.busy
            and result is not None
            and result.cancelled
            and result.error is None
            and result.process is None
            and bool(result.kept_pages)
        )

    @property
    def kept_text(self) -> str:
        """What the offer to process the kept pages says, empty when there is no offer."""
        result = self._result
        if not self.can_process_kept or result is None:
            return ""
        return (
            document_kept_text(result)
            if isinstance(result, DocumentSessionResult)
            else kept_text(result)
        )

    @property
    def process_kept_text(self) -> str:
        """The button that processes the kept pages. A button cannot show a user's text safely."""
        return PROCESS_KEPT_TEXT if self.can_process_kept else ""

    @property
    def process_kept_folder(self) -> str:
        """The folder the kept pages go to, shown beside the button as plain text."""
        if not self.can_process_kept or self._scan_folder is None:
            return ""
        return self._scan_folder

    @property
    def close_title(self) -> str:
        if self._state is State.PROCESSING:
            return CLOSE_PDF_TITLE if self._mode is Mode.DOCUMENTS else CLOSE_PROCESSING_TITLE
        return CLOSE_SCAN_TITLE

    @property
    def close_text(self) -> str:
        if self._state is State.PROCESSING:
            return CLOSE_PDF_TEXT if self._mode is Mode.DOCUMENTS else CLOSE_PROCESSING_TEXT
        return CLOSE_SCAN_TEXT

    @property
    def close_ready(self) -> bool:
        """True once a requested close may go ahead: nothing is running any more."""
        return self._close_requested and not self.busy

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def document_form(self) -> DocumentForm:
        return self._doc_form

    @property
    def documents(self) -> tuple[DocumentItem, ...]:
        return self._documents

    @property
    def ocr_available(self) -> bool:
        """True when ``ocrmypdf`` was found the last time the page looked."""
        return self._ocr_available

    @property
    def ocr_hint(self) -> str:
        """What to do about missing searchable text, empty when it is available."""
        return self._ocr_hint

    @property
    def searchable_checked(self) -> bool:
        """Whether the Searchable text box shows a tick: wanted, and possible."""
        return self._doc_form.searchable and self._ocr_available

    # -- what the user does --------------------------------------------------------------

    def set_mode(self, mode: Mode | str) -> None:
        """Switch between Photos and Documents; each keeps its own form and its own results."""
        try:
            wanted = Mode(mode)
        except ValueError:
            choices = ", ".join(choice.value for choice in Mode)
            raise ValueError(f"unknown mode {mode!r}; use one of {choices}") from None
        if wanted is self._mode:
            return
        if self.busy:
            raise ActionBlockedError(f"cannot change the mode while {self._state.value}")
        self._other_views[self._mode] = self._view()
        self._mode = wanted
        self._show(self._other_views.pop(wanted, _View()))
        if self._state in (State.DONE, State.FAILED, State.CANCELLED):
            self._state = State.READY if self._scanner_ready else State.NO_SCANNER
        self._look_for_ocr()
        self._remember(self._save_mode, wanted)
        self._changed()

    def set_document_field(self, name: str, value: object) -> None:
        """Change one field of the Documents form (the folder is the Photos form's)."""
        self._doc_form = update_document_field(self._doc_form, name, value)
        self._changed()

    def set_field(self, name: str, value: object) -> None:
        """Change one field. Only its text is checked: the disk is read by ``check_disk``."""
        keep = {} if name in _DISK_FIELDS else self._disk_errors
        self._set_form(update_field(self._form, name, value), disk=False)
        self._disk_errors = keep
        if name in _DISK_FIELDS:
            self._forget_disk_check()  # what it will say is about the text before this edit
        self._changed()

    def check_disk(self) -> None:
        """Look at the disk for the output folder and album, once the user is done editing.

        With a ``disk_check`` runner the page does not wait: the answer comes to ``on_disk``.
        """
        if self._disk_check is None:
            self._disk_errors = validate_filesystem(self._form)
        else:
            self._read_disk(self._disk_check, then_scan=self._scan_when_checked)
        self._changed()

    def check_scanner(self) -> None:
        if not self.can_check:
            raise ActionBlockedError(f"cannot look for the scanner while {self._state.value}")
        try:
            self._worker.check()
        except WorkerBusyError as error:
            self._refuse(str(error), what="Could not look for the scanner")
            return
        self._look_for_ocr()  # it may have been installed since the app started
        self._state = transition(self._state, State.CHECKING)
        self._changed()

    def start_scan(self) -> None:
        if not self.can_scan:
            raise ActionBlockedError(f"cannot start a scan now: {self._why_not_scan()}")
        if self._disk_check is None:
            self._disk_errors = validate_filesystem(self._form)  # the disk may have changed since
            self._launch_scan()
            return
        if self._disk_pending != disk_key(self._form):
            self._read_disk(self._disk_check, then_scan=True)
        else:  # the check under way (it began when the user left the field) is the one to wait for
            self._scan_when_checked = True
        self._changed()  # either way the scan starts at ``on_disk``

    def _launch_scan(self) -> None:
        """The scan, once the disk has been looked at again for it."""
        if self.errors:
            self._refuse("; ".join(self.errors.values()))
            return
        self._remember_form()
        try:
            self._begin_scan()
        except FormInvalidError as error:  # it looked again and the form had gone bad
            self._disk_errors = {**self._disk_errors, **error.errors}
            self._refuse("; ".join(error.errors.values()))
            return
        except WorkerBusyError as error:
            self._refuse(str(error))
            return
        self._state = transition(self._state, State.SCANNING)
        destination = self.destination
        self._scan_folder = None if destination is None else str(Path(destination).parent)
        self._pages = 0
        self._no_pdf_progress()
        self._checking_scanner = False
        self._photos = ()
        self._documents = ()
        self._banner = None
        self._result = None
        self._changed()

    def cancel(self) -> None:
        if self.starting_scan:  # no job yet: give up waiting for the folder (it may hang)
            self._forget_disk_check()
            self._changed()
            return
        if not self.can_cancel:
            raise ActionBlockedError(f"nothing to cancel while {self._state.value}")
        self._state = transition(self._state, State.CANCELLING)
        self._worker.cancel()
        self._changed()

    def process_kept(self) -> None:
        kept = self._result
        if not self.can_process_kept or kept is None:
            raise ActionBlockedError("there are no kept pages to process")
        try:
            self._worker.process_kept(kept)
        except WorkerBusyError as error:
            self._refuse(str(error), what="Could not process the pages")
            return
        self._state = transition(self._state, State.PROCESSING)
        self._no_pdf_progress()
        self._banner = None
        # Offered once: if this fails part-way some photos are written, and a second go
        # would write them again. The folder is still known for the error message.
        self._result = replace(kept, kept_pages=())
        self._changed()

    def fail(self, error: BaseException, *, job: bool = False) -> None:
        """An unexpected error in the page itself: show it and leave a usable state.

        ``job`` says the error came from handling the running job's own report: that job is
        stopped. Any other error leaves a healthy running job alone (its page keeps its state).
        """
        logger.error("the scan page failed: %s", error, exc_info=error)
        if job:
            try:
                self._worker.cancel()
            except Exception:
                logger.exception("could not stop the job after the page failed")
        self._banner = error_banner(error)
        if job or not self.busy:
            self._state = State.FAILED
        self._changed()

    def request_close(self) -> bool:
        """True when the window may close now; otherwise cancels and waits (``close_ready``)."""
        if self._state in _RUNNING:
            self.cancel()
        elif self._state is not State.CANCELLING:
            self._forget_disk_check()  # a scan must not start after the window may close
            return True
        self._close_requested = True
        return False

    # -- what the worker reports ---------------------------------------------------------

    def on_scanner(self, error: Exception | None) -> None:
        if self._state is not State.CHECKING:
            logger.debug("ignoring a late scanner answer while %s", self._state.value)
            return
        self._set_scanner(error)
        self._state = transition(self._state, State.READY if error is None else State.NO_SCANNER)
        self._changed()

    def on_disk(self, key: DiskKey, errors: dict[str, str]) -> None:
        """What the disk said about the folder and album ``key`` stands for."""
        if key != self._disk_pending:
            return self._drop("folder check")
        self._disk_pending = None
        self._disk_errors = errors
        if self._scan_when_checked:
            self._scan_when_checked = False
            self._launch_scan()
        else:
            self._changed()

    def on_stage(self, stage: Stage) -> None:
        if stage is Stage.PROCESSING and self._state is State.SCANNING:
            self._checking_scanner = False
            self._no_pdf_progress()
            self._state = transition(self._state, State.PROCESSING)
            self._changed()
        elif stage is Stage.CHECKING and self._state is State.SCANNING:
            self._checking_scanner = True
            self._changed()
        elif stage is Stage.SCANNING and self._checking_scanner:
            self._checking_scanner = False
            self._changed()

    def on_build_page(self, progress: tuple[int, int]) -> None:
        """The PDF is on page ``number`` of ``total``."""
        if self._state not in _REPORTING:
            return self._drop("PDF page")
        self._pdf_page, self._pdf_total = progress
        self._changed()

    def on_ocr(self, running: bool = True) -> None:
        """The searchable text is being added (the bridge hands every event one value)."""
        if self._state not in _REPORTING:
            return self._drop("OCR start")
        self._ocr_running = running
        self._changed()

    def on_page(self, number: int) -> None:
        if self._state not in _REPORTING:
            return self._drop("page")
        self._pages = number
        self._checking_scanner = False
        self._changed()

    def on_photo(self, files: WrittenFiles) -> None:
        if self._state not in _REPORTING:
            return self._drop("photo")
        self._photos = (*self._photos, item_from_files(files))
        self._changed()

    def on_finished(self, result: SessionResult | DocumentSessionResult) -> None:
        if self._state not in _REPORTING:
            return self._drop("result")
        final = final_state(result)
        self._checking_scanner = False
        self._state = transition(self._state, final)
        self._result = result
        if isinstance(result, DocumentSessionResult):
            self._documents = self._documents_after(result)
            self._banner = document_result_banner(final, result)
        else:
            self._banner = result_banner(final, result)
        if _lost(result.error):
            self._set_scanner(result.error, repeated=True)
        self._changed()

    def on_error(self, error: Exception) -> None:
        if self._state not in (State.CHECKING, *_REPORTING):
            return self._drop("error")
        lost = _lost(error)
        self._checking_scanner = False
        if self._state is State.CHECKING or (lost and self._state is State.SCANNING):
            self._set_scanner(error)
            self._state = transition(self._state, State.NO_SCANNER)
        else:
            if lost:
                self._set_scanner(error, repeated=True)
            kept = self._result
            raw = (kept.raw_dir, kept.raw_reason) if kept is not None else (None, None)
            if self._mode is Mode.DOCUMENTS:
                self._banner = document_error_banner(error, *raw)
            else:
                self._banner = error_banner(error, *raw)
            self._state = transition(self._state, State.FAILED)
        self._changed()

    # -- helpers -------------------------------------------------------------------------

    def _set_form(self, form: ScanForm, *, disk: bool) -> None:
        self._form = form
        self._syntax_errors = validate_syntax(form)
        self._disk_errors = validate_filesystem(form) if disk else {}
        self._destination = destination(form)

    def _read_disk(self, check: DiskCheck, *, then_scan: bool) -> None:
        self._disk_pending, self._scan_when_checked = disk_key(self._form), then_scan
        try:
            check(self._form)
        except Exception:
            self._forget_disk_check()
            raise

    def _forget_disk_check(self) -> None:
        self._disk_pending, self._scan_when_checked = None, False

    def _refuse(self, why: str, *, what: str = "The scan did not start") -> None:
        """Something that did not start: say why, and keep the page as it was."""
        self._banner = Banner("error", f"{what}: {why.rstrip('.')}.")
        self._changed()

    def _drop(self, what: str) -> None:
        logger.debug("ignoring a late %s while %s", what, self._state.value)

    def _set_scanner(self, error: Exception | None, *, repeated: bool = False) -> None:
        """Remember what a check or a lost scanner said; ``repeated``: a banner says it already."""
        self._scanner_ready = error is None
        if error is None:
            self._scanner_message = FOUND_TEXT
        else:
            self._scanner_message = LOST_TEXT if repeated else error_text(error)

    def _why_not_scan(self) -> str:
        if self.errors:
            return f"the form has errors in {', '.join(self.errors)}"
        if not self._scanner_ready:
            return "no scanner has been found"
        return f"the page is {self._state.value}"

    def _begin_scan(self) -> None:
        """Hand the scan to the worker: the Photos form, or the Documents form and the folder."""
        if self._mode is Mode.PHOTOS:
            self._worker.scan(self._form, checked=True)
            return
        self._worker.scan_documents(
            self._doc_form,
            self._form.output_folder,
            ocr_available=self._ocr_available,
            checked=True,
        )

    def _remember_form(self) -> None:
        """Save the forms for the next run: the folder is the Photos form's, in both modes."""
        self._remember(self._save_form, self._form)
        if self._mode is Mode.DOCUMENTS:
            self._remember(self._save_doc_form, self._doc_form)

    def _remember[T](self, save: Callable[[T], None] | None, value: T) -> None:
        if save is None:
            return
        try:
            save(value)
        except OSError as error:
            logger.warning("could not remember the settings: %s", error)

    def _view(self) -> _View:
        return _View(
            self._pages,
            self._photos,
            self._documents,
            self._banner,
            self._result,
            self._scan_folder,
        )

    def _show(self, view: _View) -> None:
        self._pages, self._photos, self._documents = view.pages, view.photos, view.documents
        self._banner, self._result, self._scan_folder = view.banner, view.result, view.scan_folder
        self._no_pdf_progress()

    def _no_pdf_progress(self) -> None:
        self._pdf_page, self._pdf_total, self._ocr_running = 0, 0, False

    def _look_for_ocr(self) -> None:
        """Ask the machine for ``ocrmypdf`` again: the answer is kept until the next look."""
        self._ocr_available = self._tools.ocr_available
        self._ocr_hint = "" if self._ocr_available else self._tools.ocr_hint

    def _documents_after(self, result: DocumentSessionResult) -> tuple[DocumentItem, ...]:
        if result.document is None:
            return self._documents
        return (*self._documents, item_from_document(result.document))

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()
