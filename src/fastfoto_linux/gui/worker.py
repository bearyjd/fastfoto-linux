"""Run the scanner check and the scan session off the GUI thread, reporting to a sink."""

from collections.abc import Callable
from typing import Protocol

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import ProcessResult, process_pages  # noqa: F401
from fastfoto_linux.scanner import ScanTarget, resolve_target  # noqa: F401
from fastfoto_linux.session import SessionResult, Stage, run_session  # noqa: F401

DiscoverFn = Callable[[], ScanTarget]
SessionFn = Callable[..., SessionResult]
ProcessFn = Callable[..., ProcessResult]


class WorkerBusyError(RuntimeError):
    """A job was started while another one is still running."""


class WorkerSink(Protocol):
    """Where the worker reports; every method is called on the worker's thread."""

    def on_scanner(self, error: Exception | None) -> None: ...
    def on_stage(self, stage: Stage) -> None: ...
    def on_page(self, number: int) -> None: ...
    def on_photo(self, files: WrittenFiles) -> None: ...
    def on_finished(self, result: SessionResult) -> None: ...
    def on_error(self, error: Exception) -> None: ...


def default_discover() -> ScanTarget:
    """The USB scanner and the shim it needs; raises ScannerError when either is missing."""
    raise NotImplementedError


class Worker:
    """One background job at a time: check the scanner, scan a batch, or process kept pages."""

    def __init__(
        self,
        sink: WorkerSink,
        *,
        discover: DiscoverFn | None = None,
        session: SessionFn | None = None,
        process: ProcessFn | None = None,
    ) -> None:
        """The three collaborators default to the real ones, looked up when the worker is made."""
        raise NotImplementedError

    @property
    def busy(self) -> bool:
        raise NotImplementedError

    def check(self) -> None:
        raise NotImplementedError

    def scan(self, form: ScanForm) -> None:
        raise NotImplementedError

    def process_kept(self, kept: SessionResult) -> None:
        raise NotImplementedError

    def cancel(self) -> None:
        raise NotImplementedError

    def join(self, timeout: float | None = None) -> None:
        raise NotImplementedError
