"""Run the scanner check and the scan session off the GUI thread, reporting to a sink."""

import functools
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from fastfoto_linux.documents import (
    DocumentCancelledError,
    DocumentError,
    DocumentResult,
    build_document,
)
from fastfoto_linux.gui.docform import DocumentForm, document_errors, to_document_request
from fastfoto_linux.gui.doctools import DocumentTools
from fastfoto_linux.gui.form import (
    FormInvalidError,
    ScanForm,
    to_request,
    validate,
    validate_syntax,
)
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import ProcessResult, process_pages
from fastfoto_linux.scanner import ScanTarget, default_shim_candidates, resolve_target
from fastfoto_linux.session import (
    DocumentScanRequest,
    DocumentSessionResult,
    ScanRequest,
    SessionResult,
    Stage,
    run_document_session,
    run_session,
)

logger = logging.getLogger(__name__)

DiscoverFn = Callable[[], ScanTarget]
SessionFn = Callable[..., SessionResult]
ProcessFn = Callable[..., ProcessResult]
_Job = Callable[[threading.Event], Callable[[], None]]
"""A job runs with its cancel event and returns the one report that ends it."""


class WorkerBusyError(RuntimeError):
    """A job was started while another one is still running."""


class WorkerSink(Protocol):
    """Where the worker reports; every method is called on the worker's thread."""

    def on_scanner(self, error: Exception | None) -> None: ...
    def on_stage(self, stage: Stage) -> None: ...
    def on_page(self, number: int) -> None: ...
    def on_build_page(self, progress: tuple[int, int]) -> None: ...
    def on_ocr(self) -> None: ...
    def on_photo(self, files: WrittenFiles) -> None: ...
    def on_finished(self, result: SessionResult | DocumentSessionResult) -> None: ...
    def on_error(self, error: Exception) -> None: ...


def default_discover() -> ScanTarget:
    """The USB scanner and the shim it needs; raises ScannerError when either is missing."""
    return resolve_target(shim_candidates=default_shim_candidates(os.environ), net_host=None)


class Worker:
    """One background job at a time: check the scanner, scan a batch, or process kept pages."""

    def __init__(
        self,
        sink: WorkerSink,
        *,
        discover: DiscoverFn | None = None,
        session: SessionFn | None = None,
        process: ProcessFn | None = None,
        documents: DocumentTools | None = None,
    ) -> None:
        """The three collaborators default to the real ones, looked up when the worker is made."""
        self._sink = sink
        self._discover = default_discover if discover is None else discover
        self._session = run_session if session is None else session
        self._process = process_pages if process is None else process
        self._lock = threading.Lock()
        self._busy = False
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._request: ScanRequest | None = None
        self._document_request: DocumentScanRequest | None = None
        tools = documents or DocumentTools()
        self._document_session = run_document_session if tools.session is None else tools.session
        self._build = build_document if tools.build is None else tools.build

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def check(self) -> None:
        """Look for the scanner; ``on_scanner`` hears the answer (None: found)."""

        def job(cancel: threading.Event) -> Callable[[], None]:
            try:
                self._discover()
            except Exception as error:
                logger.info("no scanner: %s", error)
                return functools.partial(self._sink.on_scanner, error)
            return functools.partial(self._sink.on_scanner, None)

        self._start(job)

    def scan(self, form: ScanForm, *, checked: bool = False) -> None:
        """Scan with the form's settings. Raises FormInvalidError before anything starts.

        ``checked``: the caller has just read the disk for this form, so only the form's text is
        looked at here, on the caller's thread (the job looks at the disk again on its own).
        """
        errors = validate_syntax(form) if checked else validate(form)
        if errors:
            raise FormInvalidError(errors)
        self._start(lambda cancel: self._scan(form, cancel))

    def scan_documents(
        self, form: DocumentForm, folder: str, *, ocr_available: bool, checked: bool = False
    ) -> None:
        """Scan a document with the form's settings. Raises FormInvalidError before it starts.

        ``checked`` is as for ``scan``. The folder's existence is not looked at again in the job:
        the session refuses a missing one before it scans anything, and its message is the
        authority.
        """
        errors = document_errors(form, folder, disk=not checked)
        if errors:
            raise FormInvalidError(errors)
        self._start(lambda cancel: self._scan_documents(form, folder, ocr_available, cancel))

    def process_kept(self, kept: SessionResult | DocumentSessionResult) -> None:
        """Process the raw pages a cancelled scan kept, with the settings of the last scan."""
        if isinstance(kept, DocumentSessionResult):
            document_request = self._document_request
            if document_request is None:
                raise RuntimeError("no scan has run, so there are no settings to make the PDF")
            self._start(lambda cancel: self._make_kept(kept, document_request, cancel))
            return
        request = self._request
        if request is None:
            raise RuntimeError("no scan has run, so there are no settings to process the pages")
        self._start(lambda cancel: self._process_kept(kept, request, cancel))

    def cancel(self) -> None:
        """Ask the running job to stop; harmless when nothing runs."""
        self._cancel.set()

    @property
    def alive(self) -> bool:
        """True while the job's thread is still running (it may have been cancelled already)."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _start(self, job: _Job) -> None:
        with self._lock:
            if self._busy:
                raise WorkerBusyError("the scanner is busy with another job")
            self._busy = True
            self._cancel = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(job, self._cancel), name="fastfoto-worker", daemon=True
            )
        self._thread.start()

    def _run(self, job: _Job, cancel: threading.Event) -> None:
        try:
            report = job(cancel)
        except Exception as error:
            logger.exception("the background job failed")
            report = functools.partial(self._sink.on_error, error)
        with self._lock:  # idle before the end is reported, so the next job can start at once
            self._busy = False
        try:
            report()
        except Exception:
            logger.exception("the final report to the window failed")

    def _scan(self, form: ScanForm, cancel: threading.Event) -> Callable[[], None]:
        request = to_request(form, self._discover())
        self._request = request
        sink = self._sink
        result = self._session(
            request,
            on_page=sink.on_page,
            on_photo=sink.on_photo,
            on_stage=sink.on_stage,
            cancel=cancel,
        )
        return functools.partial(sink.on_finished, result)

    def _process_kept(
        self, kept: SessionResult, request: ScanRequest, cancel: threading.Event
    ) -> Callable[[], None]:
        self._sink.on_stage(Stage.PROCESSING)
        processed = self._process(
            kept.kept_pages, request.settings, on_photo=self._sink.on_photo, cancel=cancel
        )
        result = SessionResult(
            process=processed,
            pages_scanned=len(kept.kept_pages),
            raw_dir=kept.raw_dir,
            raw_reason=kept.raw_reason,
            cancelled=processed.cancelled,
        )
        return functools.partial(self._sink.on_finished, result)

    def _scan_documents(
        self, form: DocumentForm, folder: str, ocr_available: bool, cancel: threading.Event
    ) -> Callable[[], None]:
        request = to_document_request(
            form, folder, self._discover(), ocr_available=ocr_available, check_disk=False
        )
        self._document_request = request
        result = self._document_session(
            request,
            on_page=self._sink.on_page,
            on_stage=self._sink.on_stage,
            cancel=cancel,
            build=self._reporting_build(),
        )
        return functools.partial(self._sink.on_finished, result)

    def _reporting_build(self) -> Callable[..., DocumentResult]:
        """The PDF builder, telling the sink which page it is on and when the OCR starts."""
        return functools.partial(
            self._build,
            on_page=lambda number, total: self._sink.on_build_page((number, total)),
            on_ocr=self._sink.on_ocr,
        )

    def _make_kept(
        self, kept: DocumentSessionResult, request: DocumentScanRequest, cancel: threading.Event
    ) -> Callable[[], None]:
        """Make the PDF of the pages a part-way scan kept, with the settings of that scan.

        A PDF that cannot be made comes back as a result (the pages are still on disk), not as an
        exception, so the page can say so and keep the pages where they are.
        """
        self._sink.on_stage(Stage.PROCESSING)
        settings = replace(request.settings, fallback_dpi=request.dpi)
        again = replace(kept, document=None, error=None, cancelled=False)
        try:
            document = self._reporting_build()(kept.kept_pages, settings, cancel=cancel)
        except DocumentCancelledError:
            result = replace(again, cancelled=True)
        except DocumentError as error:
            result = replace(again, error=error)
        else:
            result = replace(again, document=document, kept_pages=())
        return functools.partial(self._sink.on_finished, result)
