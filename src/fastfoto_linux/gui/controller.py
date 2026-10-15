"""The logic of the scan page, free of Qt: the form, the state and what the results say.

The controller is a worker sink whose methods must be called on one thread (the GUI's). A front
end that runs the worker on another thread hands every sink call over to that thread first.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.photos import PhotoItem
from fastfoto_linux.gui.report import Banner
from fastfoto_linux.gui.state import State
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.session import SessionResult, Stage


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
        raise NotImplementedError

    @property
    def state(self) -> State:
        raise NotImplementedError

    @property
    def form(self) -> ScanForm:
        raise NotImplementedError

    @property
    def errors(self) -> dict[str, str]:
        raise NotImplementedError

    @property
    def destination(self) -> str | None:
        raise NotImplementedError

    @property
    def scanner_text(self) -> str:
        raise NotImplementedError

    @property
    def progress_text(self) -> str:
        raise NotImplementedError

    @property
    def photos(self) -> tuple[PhotoItem, ...]:
        raise NotImplementedError

    @property
    def results_folder(self) -> Path | None:
        """The folder the latest photo was written to, None before there is one."""
        raise NotImplementedError

    @property
    def banner(self) -> Banner | None:
        raise NotImplementedError

    @property
    def busy(self) -> bool:
        raise NotImplementedError

    @property
    def can_scan(self) -> bool:
        raise NotImplementedError

    @property
    def can_cancel(self) -> bool:
        raise NotImplementedError

    @property
    def can_check(self) -> bool:
        raise NotImplementedError

    @property
    def can_process_kept(self) -> bool:
        raise NotImplementedError

    @property
    def close_ready(self) -> bool:
        """True once a requested close may go ahead: nothing is running any more."""
        raise NotImplementedError

    def set_field(self, name: str, value: object) -> None:
        raise NotImplementedError

    def check_scanner(self) -> None:
        raise NotImplementedError

    def start_scan(self) -> None:
        raise NotImplementedError

    def cancel(self) -> None:
        raise NotImplementedError

    def process_kept(self) -> None:
        raise NotImplementedError

    def request_close(self) -> bool:
        """True when the window may close now; otherwise cancels and waits (``close_ready``)."""
        raise NotImplementedError

    def on_scanner(self, error: Exception | None) -> None:
        raise NotImplementedError

    def on_stage(self, stage: Stage) -> None:
        raise NotImplementedError

    def on_page(self, number: int) -> None:
        raise NotImplementedError

    def on_photo(self, files: WrittenFiles) -> None:
        raise NotImplementedError

    def on_finished(self, result: SessionResult) -> None:
        raise NotImplementedError

    def on_error(self, error: Exception) -> None:
        raise NotImplementedError
