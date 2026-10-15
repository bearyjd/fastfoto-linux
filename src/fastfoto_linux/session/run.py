"""Run one scan session: scan into a raw folder, process the pages, settle the raw pages.

The flow of ``ffscan scan``, free of any front end: nothing here prints, reads the command line,
installs signal handlers or exits. A front end passes callbacks in and reads a
:class:`SessionResult` out; a CLI turns signals into an interrupt, a GUI sets a cancel event.
"""

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import ProcessResult, ProcessSettings, process_pages
from fastfoto_linux.scanner import (
    ScanCancelledError,
    ScanError,
    ScanJob,
    ScannerError,
    ScanResult,
    Source,
    run_scan,
)
from fastfoto_linux.session.raw import (
    create_raw_dir,
    is_complete_png,
    list_pages,
    settle_raw_dir,
)
from fastfoto_linux.session.request import RawPolicy, ScanRequest
from fastfoto_linux.session.result import RawReason, SessionResult, Stage

logger = logging.getLogger(__name__)

ScanFn = Callable[..., ScanResult]
"""``run_scan``'s call shape: ``(job, *, env, on_progress, cancel) -> ScanResult``."""
ProcessFn = Callable[..., ProcessResult]
"""``process_pages``' call shape; ``on_photo`` and ``cancel`` are passed only when given."""


@dataclass(frozen=True)
class _Hooks:
    """The callbacks and collaborators of one session, so they travel as one argument."""

    scan: ScanFn
    process: ProcessFn
    on_page: Callable[[int], None] | None
    on_photo: Callable[[WrittenFiles], None] | None
    on_stage: Callable[[Stage], None] | None
    cancel: threading.Event | None

    def stage(self, stage: Stage) -> None:
        if self.on_stage is not None:
            self.on_stage(stage)


@dataclass(frozen=True)
class _Scanned:
    """What the scan left: the pages, and why it stopped early if it did."""

    pages: tuple[Path, ...] = ()
    error: ScanError | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class _Outcome:
    """How the scan and the processing ended, before the raw pages are settled."""

    pages: tuple[Path, ...] = ()
    process: ProcessResult | None = None
    error: Exception | None = None
    cancelled: bool = False


def run_session(  # noqa: PLR0913 - the callbacks are the interface; scan/process are test seams
    request: ScanRequest,
    *,
    on_page: Callable[[int], None] | None = None,
    on_photo: Callable[[WrittenFiles], None] | None = None,
    on_stage: Callable[[Stage], None] | None = None,
    cancel: threading.Event | None = None,
    scan: ScanFn | None = None,
    process: ProcessFn | None = None,
) -> SessionResult:
    """Scan the document feeder, process the pages and settle the raw pages.

    All callbacks run on the thread that called ``run_session``, so a GUI calls it from a
    worker and hands the callbacks' arguments to its own thread. ``on_stage`` hears
    SCANNING, then PROCESSING (unless the scan was cancelled or failed without pages), then
    DONE, once the raw pages are settled. ``on_page(number)`` fires as each page is finished
    (see ``run_scan``); ``on_photo(files)`` as each photo is written (see ``process_pages``).
    Callbacks should be quick: the scanner is not watched, and the next sheet is not processed,
    while they run.

    Setting ``cancel`` (from any thread) stops scanimage. A cancel during the scan processes
    nothing, as Ctrl-C always did in ``ffscan scan``: the pages it had finished stay in the raw
    folder, ``process`` is None, and ``SessionResult.kept_pages`` lists them, so that a front end
    can offer to process the pages scanned so far later. A cancel during processing stops it
    between sheets: the photos already written stay (``process`` lists them). A cancel that
    arrives while the last sheet is being handled finds nothing left to stop: the result is
    complete, ``cancelled`` is False and the raw pages are settled as the policy says. Whenever
    something was stopped the raw pages are kept and the result says ``cancelled``. A
    ``KeyboardInterrupt`` is treated as the same cancel that cannot be undone, so a front end
    that turns signals into one gets its raw pages settled too.

    An ``OSError`` is raised if the raw folder cannot be created, before anything is scanned.
    After that no ``Exception`` is raised: one from the scanner, from processing or from a
    callback ends the session and comes back as ``SessionResult.error``, after the raw pages
    are settled. The DONE callback runs after that, so its exception is folded into the result
    instead (an earlier error stays the error). A scanner error that left finished pages is
    processed first, as ``ffscan scan`` always did. An exception that is not an ``Exception``
    (``SystemExit``, ``asyncio.CancelledError``, a private abort) cannot come back as a result,
    so it propagates, but only after the raw pages are moved to ``.raw/<stamp>/`` and logged.
    ``scan`` and ``process`` replace ``run_scan`` and ``process_pages`` (for tests, or a front
    end that must wrap them).
    """
    hooks = _Hooks(
        scan=run_scan if scan is None else scan,
        process=process_pages if process is None else process,
        on_page=on_page,
        on_photo=on_photo,
        on_stage=on_stage,
        cancel=cancel,
    )
    raw = create_raw_dir(request.raw_root, keep=request.raw_policy is RawPolicy.KEEP)
    try:
        outcome = _work(request, raw, hooks)
    except BaseException as abort:  # not an Exception: it cannot come back as a result
        _keep_after_abort(raw, request.raw_root, abort)
        raise
    return _announce_done(_settle(request, raw, outcome), hooks)


def _keep_after_abort(raw: Path, root: Path, abort: BaseException) -> None:
    """Keep the raw pages while ``abort`` is on its way; failing to must not replace it."""
    try:
        kept = settle_raw_dir(raw, root, keep=True)
    except Exception:
        logger.exception("the raw pages in %s could not be settled while aborting", raw)
        return
    if kept is not None:
        logger.error("aborted by %s; the raw pages are kept in %s", type(abort).__name__, kept)


def _settle(request: ScanRequest, raw: Path, outcome: _Outcome) -> SessionResult:
    """Keep or delete the raw pages as the outcome and the policy say, and report it."""
    reason = _keep_reason(request.raw_policy, outcome)
    kept = settle_raw_dir(
        raw, request.raw_root, keep=reason is not None, album=request.settings.output_root
    )
    if kept is not None and reason is None:
        reason = RawReason.NOT_DELETED
    return SessionResult(
        process=outcome.process,
        pages_scanned=len(outcome.pages),
        raw_dir=kept,
        raw_reason=reason if kept is not None else None,
        error=outcome.error,
        cancelled=outcome.cancelled,
        kept_pages=() if kept is None else _finished_pages(kept, outcome.pages),
    )


def _finished_pages(kept: Path, reported: tuple[Path, ...]) -> tuple[Path, ...]:
    """The pages in ``kept`` the scanner finished: complete PNGs, and only the reported ones
    when the scan reported any (a cancel or a kill can leave the last page cut off mid-write,
    and ``run_scan`` reports every page file it finds)."""
    finished = {page.name for page in reported}
    return tuple(
        page
        for page in list_pages(kept)
        if (not finished or page.name in finished) and is_complete_png(page)
    )


def _announce_done(result: SessionResult, hooks: _Hooks) -> SessionResult:
    """Tell the DONE stage; a callback that raises costs the result nothing."""
    try:
        hooks.stage(Stage.DONE)
    except Exception as error:
        logger.exception("the DONE callback raised; the result is returned anyway")
        return replace(result, error=error if result.error is None else result.error)
    return result


def _work(request: ScanRequest, raw: Path, hooks: _Hooks) -> _Outcome:
    """Scan into ``raw`` and process what was scanned; never raises an ``Exception``."""
    scanned = _Scanned()
    try:
        hooks.stage(Stage.SCANNING)
        scanned = _scan(request, raw, hooks)
        if scanned.cancelled:
            return _Outcome(scanned.pages, cancelled=True)
        hooks.stage(Stage.PROCESSING)
        processed = _process(scanned.pages, request.settings, hooks)
    except KeyboardInterrupt:  # the front end's signal handler: stop, the pages stay
        logger.debug("the session was interrupted", exc_info=True)
        return _Outcome(scanned.pages, cancelled=True)
    except Exception as error:
        logger.debug("the session ended by an exception", exc_info=True)
        return _Outcome(scanned.pages, error=error)
    return _Outcome(scanned.pages, processed, scanned.error, processed.cancelled)


def _scan(request: ScanRequest, raw: Path, hooks: _Hooks) -> _Scanned:
    """Run the scan. A scanner failure part-way keeps the pages finished before it."""
    job = ScanJob(
        device=request.target.device,
        output_dir=raw,
        source=Source.DUPLEX if request.duplex else Source.FRONT,
        resolution=request.dpi,
    )
    env = request.target.env(os.environ)
    try:
        result = hooks.scan(job, env=env, on_progress=hooks.on_page, cancel=hooks.cancel)
    except ScanCancelledError as error:
        return _Scanned(error.pages, cancelled=True)
    except ScanError as error:
        if not error.pages:
            raise
        logger.error("the scan stopped early; processing the %d finished pages", len(error.pages))
        return _Scanned(error.pages, error=error)
    return _Scanned(result.pages)


def _process(pages: tuple[Path, ...], settings: ProcessSettings, hooks: _Hooks) -> ProcessResult:
    """Process the pages, handing ``on_photo`` and ``cancel`` over only when there are any."""
    options: dict[str, Any] = {}
    if hooks.on_photo is not None:
        options["on_photo"] = hooks.on_photo
    if hooks.cancel is not None:
        options["cancel"] = hooks.cancel
    return hooks.process(pages, settings, **options)


def _keep_reason(policy: RawPolicy, outcome: _Outcome) -> RawReason | None:
    """Why the raw pages must stay, or None when they may go: only a clean run lets them go."""
    reason = _failure_reason(outcome)
    return reason if reason is not None else _policy_reason(policy, outcome.process)


def _failure_reason(outcome: _Outcome) -> RawReason | None:
    """The reason when the run was not clean; a lost page means scanning the print again."""
    processed = outcome.process
    if outcome.cancelled:
        return RawReason.CANCELLED
    if outcome.error is not None:
        return RawReason.SCAN_ERROR if isinstance(outcome.error, ScannerError) else RawReason.ERROR
    if processed is None:  # no result and no known cause: the run ended early, the pages stay
        return RawReason.ERROR
    if processed.failed:
        return RawReason.SHEETS_FAILED
    if processed.degraded:
        return RawReason.SHEETS_DEGRADED
    return None


def _policy_reason(policy: RawPolicy, processed: ProcessResult | None) -> RawReason | None:
    """The reason when the run was clean: asked for, or a back was dropped.

    A dropped back keeps the pages too (unless the policy is DISCARD), so that a back with
    faint writing is never lost for good.
    """
    if policy is RawPolicy.KEEP:
        return RawReason.REQUESTED
    if processed is not None and processed.backs_dropped and policy is not RawPolicy.DISCARD:
        return RawReason.BACK_DROPPED
    return None
