"""The logic of the scan page, free of Qt: the form, the state and what the results say.

The controller is a worker sink whose methods must be called on one thread (the GUI's). A front
end that runs the worker on another thread hands every sink call over to that thread first.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from fastfoto_linux.gui.form import ScanForm, destination, update_field, validate
from fastfoto_linux.gui.photos import PhotoItem, item_from_files
from fastfoto_linux.gui.report import (
    Banner,
    error_banner,
    error_text,
    progress_text,
    result_banner,
)
from fastfoto_linux.gui.state import (
    InvalidTransitionError,
    State,
    can_cancel,
    final_state,
    is_busy,
    transition,
)
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.scanner import ScannerError, ScannerNotFoundError, ShimMissingError
from fastfoto_linux.session import SessionResult, Stage

logger = logging.getLogger(__name__)

_SCANNABLE = frozenset({State.READY, State.DONE, State.FAILED, State.CANCELLED})
_KEPT_OFFERED = frozenset({State.FAILED, State.CANCELLED})
_RUNNING = (State.SCANNING, State.PROCESSING)
NOT_CHECKED = "The scanner has not been checked yet."
CHECKING_TEXT = "Looking for the scanner…"
FOUND_TEXT = "Scanner found."


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
    ) -> None:
        self._worker = worker
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
        self._set_form(form or ScanForm())

    # -- what the page shows -------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def form(self) -> ScanForm:
        return self._form

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

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
        return self._state in _SCANNABLE and self._scanner_ready and not self._errors

    @property
    def can_cancel(self) -> bool:
        return can_cancel(self._state)

    @property
    def can_check(self) -> bool:
        return not self.busy

    @property
    def can_process_kept(self) -> bool:
        result = self._result
        return (
            self._state in _KEPT_OFFERED
            and result is not None
            and result.process is None
            and bool(result.kept_pages)
        )

    @property
    def close_ready(self) -> bool:
        """True once a requested close may go ahead: nothing is running any more."""
        return self._close_requested and not self.busy

    # -- what the user does --------------------------------------------------------------

    def set_field(self, name: str, value: object) -> None:
        self._set_form(update_field(self._form, name, value))
        self._changed()

    def check_scanner(self) -> None:
        if not self.can_check:
            raise InvalidTransitionError(f"cannot look for the scanner while {self._state.value}")
        self._worker.check()
        self._state = transition(self._state, State.CHECKING)
        self._changed()

    def start_scan(self) -> None:
        if not self.can_scan:
            raise InvalidTransitionError(f"cannot start a scan now: {self._why_not_scan()}")
        self._remember_form()
        self._worker.scan(self._form)
        self._state = transition(self._state, State.SCANNING)
        self._pages = 0
        self._photos = ()
        self._banner = None
        self._result = None
        self._changed()

    def cancel(self) -> None:
        if not self.can_cancel:
            raise InvalidTransitionError(f"nothing to cancel while {self._state.value}")
        self._state = transition(self._state, State.CANCELLING)
        self._worker.cancel()
        self._changed()

    def process_kept(self) -> None:
        kept = self._result
        if not self.can_process_kept or kept is None:
            raise InvalidTransitionError("there are no kept pages to process")
        self._worker.process_kept(kept)
        self._state = transition(self._state, State.PROCESSING)
        self._banner = None
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

    def on_stage(self, stage: Stage) -> None:
        if stage is Stage.PROCESSING and self._state is State.SCANNING:
            self._state = transition(self._state, State.PROCESSING)
            self._changed()

    def on_page(self, number: int) -> None:
        self._pages = number
        self._changed()

    def on_photo(self, files: WrittenFiles) -> None:
        self._photos = (*self._photos, item_from_files(files))
        self._changed()

    def on_finished(self, result: SessionResult) -> None:
        final = final_state(result)
        self._state = transition(self._state, final)
        self._result = result
        self._banner = result_banner(final, result)
        if isinstance(result.error, ScannerError):
            self._set_scanner(result.error)
        self._changed()

    def on_error(self, error: Exception) -> None:
        lost = isinstance(error, ScannerNotFoundError | ShimMissingError)
        if self._state is State.CHECKING or (lost and self._state is State.SCANNING):
            self._set_scanner(error)
            self._state = transition(self._state, State.NO_SCANNER)
        else:
            if isinstance(error, ScannerError):
                self._set_scanner(error)
            self._banner = error_banner(error)
            self._state = transition(self._state, State.FAILED)
        self._changed()

    # -- helpers -------------------------------------------------------------------------

    def _set_form(self, form: ScanForm) -> None:
        self._form = form
        self._errors = validate(form)
        self._destination = destination(form)

    def _set_scanner(self, error: Exception | None) -> None:
        self._scanner_ready = error is None
        self._scanner_message = FOUND_TEXT if error is None else error_text(error)

    def _why_not_scan(self) -> str:
        if self._errors:
            return f"the form has errors in {', '.join(self._errors)}"
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
