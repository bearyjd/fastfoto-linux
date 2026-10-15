"""The logic of the scan page, free of Qt: the form, the state and what the results say.

The controller is a worker sink whose methods must be called on one thread (the GUI's). A front
end that runs the worker on another thread hands every sink call over to that thread first.
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

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
    State,
    can_cancel,
    final_state,
    is_busy,
    transition,
)
from fastfoto_linux.gui.worker import WorkerBusyError
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.scanner import ScannerNotFoundError, ShimMissingError
from fastfoto_linux.session import SessionResult, Stage

logger = logging.getLogger(__name__)

_SCANNABLE = frozenset({State.READY, State.DONE, State.FAILED, State.CANCELLED})
_RUNNING = (State.SCANNING, State.PROCESSING)
_REPORTING = frozenset({State.SCANNING, State.PROCESSING, State.CANCELLING})
_DISK_FIELDS = frozenset({"output_folder", "album"})
CHECKING_DISK_TEXT = "Checking the folder…"
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


DiskKey = tuple[str, str]
DiskCheck = Callable[[ScanForm], None]
"""Starts reading the disk for a form and returns at once; the answer goes to ``on_disk``."""


def disk_key(form: ScanForm) -> DiskKey:
    """What a read of the disk depends on: the output folder and the album."""
    return (form.output_folder.strip(), form.album.strip())


def _lost(error: BaseException | None) -> bool:
    """True when the scanner itself is gone; a jam or an empty feeder leaves it found."""
    return isinstance(error, ScannerNotFoundError | ShimMissingError)


class WorkerPort(Protocol):
    """What the controller asks of the worker."""

    def check(self) -> None: ...
    def scan(self, form: ScanForm) -> None: ...
    def process_kept(self, kept: SessionResult) -> None: ...
    def cancel(self) -> None: ...


class Controller:
    """The scan page's state, form and results; ``on_change`` hears every change."""

    def __init__(
        self,
        worker: WorkerPort,
        form: ScanForm | None = None,
        *,
        save_form: Callable[[ScanForm], None] | None = None,
        on_change: Callable[[], None] | None = None,
        disk_check: DiskCheck | None = None,
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
        self._result: SessionResult | None = None
        self._close_requested = False
        self._scan_folder: str | None = None
        self._disk_errors: dict[str, str] = {}
        self._set_form(form or ScanForm(), disk=True)

    # -- what the page shows -------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def form(self) -> ScanForm:
        return self._form

    @property
    def errors(self) -> dict[str, str]:
        """A message per bad field: the text checked at every edit, the disk when it was read."""
        return merge_errors(self._syntax_errors, self._disk_errors)

    @property
    def destination(self) -> str | None:
        return self._destination

    @property
    def scanner_text(self) -> str:
        return CHECKING_TEXT if self._state is State.CHECKING else self._scanner_message

    @property
    def progress_text(self) -> str:
        return progress_text(self._state, self._pages, len(self._photos))

    @property
    def photos(self) -> tuple[PhotoItem, ...]:
        return self._photos

    @property
    def results_folder(self) -> Path | None:
        """The folder the latest photo was written to, None before there is one."""
        return self._photos[-1].directory if self._photos else None

    @property
    def banner(self) -> Banner | None:
        return self._banner

    @property
    def busy(self) -> bool:
        return is_busy(self._state)

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
        return self._state in _SCANNABLE and self._scanner_ready and not self.errors

    @property
    def scan_blocker(self) -> str:
        """Why Scan is disabled, in words for the user; empty when it is enabled or a job runs."""
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
    def can_check(self) -> bool:
        return not self.busy

    @property
    def can_process_kept(self) -> bool:
        """True while the last result is a cancelled scan whose raw pages are waiting."""
        result = self._result
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
        return kept_text(result) if self.can_process_kept and result is not None else ""

    @property
    def process_kept_text(self) -> str:
        """The button that processes the kept pages: it names the folder they go to."""
        if not self.can_process_kept or self._scan_folder is None:
            return ""
        return f"Process them now into {self._scan_folder}"

    @property
    def close_title(self) -> str:
        return CLOSE_PROCESSING_TITLE if self._state is State.PROCESSING else CLOSE_SCAN_TITLE

    @property
    def close_text(self) -> str:
        return CLOSE_PROCESSING_TEXT if self._state is State.PROCESSING else CLOSE_SCAN_TEXT

    @property
    def close_ready(self) -> bool:
        """True once a requested close may go ahead: nothing is running any more."""
        return self._close_requested and not self.busy

    # -- what the user does --------------------------------------------------------------

    def set_field(self, name: str, value: object) -> None:
        """Change one field. Only its text is checked: the disk is read by ``check_disk``."""
        keep = {} if name in _DISK_FIELDS else self._disk_errors
        self._set_form(update_field(self._form, name, value), disk=False)
        self._disk_errors = keep
        self._changed()

    def check_disk(self) -> None:
        """Look at the disk for the output folder and album, once the user is done editing."""
        self._disk_errors = validate_filesystem(self._form)
        self._changed()

    def check_scanner(self) -> None:
        if not self.can_check:
            raise ActionBlockedError(f"cannot look for the scanner while {self._state.value}")
        try:
            self._worker.check()
        except WorkerBusyError as error:
            self._refuse(str(error), what="Could not look for the scanner")
            return
        self._state = transition(self._state, State.CHECKING)
        self._changed()

    def start_scan(self) -> None:
        if not self.can_scan:
            raise ActionBlockedError(f"cannot start a scan now: {self._why_not_scan()}")
        self._disk_errors = validate_filesystem(self._form)  # the disk may have changed since
        if self.errors:
            self._refuse("; ".join(self.errors.values()))
            return
        self._remember_form()
        try:
            self._worker.scan(self._form)
        except FormInvalidError as error:  # it looked again and the form had gone bad
            self._disk_errors = {**self._disk_errors, **error.errors}
            self._refuse("; ".join(error.errors.values()))
            return
        except WorkerBusyError as error:
            self._refuse(str(error))
            return
        self._state = transition(self._state, State.SCANNING)
        self._scan_folder = (
            None if self._destination is None else str(Path(self._destination).parent)
        )
        self._pages = 0
        self._photos = ()
        self._banner = None
        self._result = None
        self._changed()

    def cancel(self) -> None:
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
        raise NotImplementedError

    def on_stage(self, stage: Stage) -> None:
        if stage is Stage.PROCESSING and self._state is State.SCANNING:
            self._state = transition(self._state, State.PROCESSING)
            self._changed()

    def on_page(self, number: int) -> None:
        if self._state not in _REPORTING:
            return self._drop("page")
        self._pages = number
        self._changed()

    def on_photo(self, files: WrittenFiles) -> None:
        if self._state not in _REPORTING:
            return self._drop("photo")
        self._photos = (*self._photos, item_from_files(files))
        self._changed()

    def on_finished(self, result: SessionResult) -> None:
        if self._state not in _REPORTING:
            return self._drop("result")
        final = final_state(result)
        self._state = transition(self._state, final)
        self._result = result
        self._banner = result_banner(final, result)
        if _lost(result.error):
            self._set_scanner(result.error, repeated=True)
        self._changed()

    def on_error(self, error: Exception) -> None:
        if self._state not in (State.CHECKING, *_REPORTING):
            return self._drop("error")
        lost = _lost(error)
        if self._state is State.CHECKING or (lost and self._state is State.SCANNING):
            self._set_scanner(error)
            self._state = transition(self._state, State.NO_SCANNER)
        else:
            if lost:
                self._set_scanner(error, repeated=True)
            kept = self._result
            raw = (kept.raw_dir, kept.raw_reason) if kept is not None else (None, None)
            self._banner = error_banner(error, *raw)
            self._state = transition(self._state, State.FAILED)
        self._changed()

    # -- helpers -------------------------------------------------------------------------

    def _set_form(self, form: ScanForm, *, disk: bool) -> None:
        self._form = form
        self._syntax_errors = validate_syntax(form)
        self._disk_errors = validate_filesystem(form) if disk else {}
        self._destination = destination(form)

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

    def _remember_form(self) -> None:
        if self._save_form is None:
            return
        try:
            self._save_form(self._form)
        except OSError as error:
            logger.warning("could not remember the settings: %s", error)

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()
