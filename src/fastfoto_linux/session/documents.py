"""Run one document scan session: scan into a raw folder, make the PDF, settle the raw pages.

The flow of ``ffscan doc scan``, free of any front end: nothing here prints, reads the command
line, installs signal handlers or exits. It is to documents what ``run_session`` is to photos and
shares with it (``session.scanning``) everything about scanning and about the raw pages.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from fastfoto_linux.documents import (
    DocumentCancelledError,
    DocumentResult,
    DocumentSettingsError,
    build_document,
    check_settings,
)
from fastfoto_linux.scanner import ScannerError, run_scan
from fastfoto_linux.scanner.precheck import check_scanner
from fastfoto_linux.session.raw import create_raw_dir, settle_raw_dir
from fastfoto_linux.session.request import DocumentScanRequest, RawPolicy
from fastfoto_linux.session.result import DocumentRawReason, DocumentSessionResult, Stage
from fastfoto_linux.session.scanning import (
    PrecheckFn,
    ScanFn,
    SessionHooks,
    announce_done,
    keep_after_abort,
    scan_pages,
    settle_pages,
)

logger = logging.getLogger(__name__)

BuildFn = Callable[..., DocumentResult]
"""``build_document``'s call shape: ``(pages, settings, *, cancel) -> DocumentResult``."""


@dataclass(frozen=True)
class _Hooks(SessionHooks):
    build: BuildFn


@dataclass(frozen=True)
class _Outcome:
    """How the scan and the PDF ended, before the raw pages are settled."""

    pages: tuple[Path, ...] = ()
    document: DocumentResult | None = None
    error: Exception | None = None
    cancelled: bool = False


def run_document_session(  # noqa: PLR0913 - the callbacks are the interface; scan/build are seams
    request: DocumentScanRequest,
    *,
    on_page: Callable[[int], None] | None = None,
    on_stage: Callable[[Stage], None] | None = None,
    cancel: threading.Event | None = None,
    scan: ScanFn | None = None,
    build: BuildFn | None = None,
    precheck: PrecheckFn | None = None,
) -> DocumentSessionResult:
    """Scan the document feeder, make one PDF of the pages and settle the raw pages.

    The callbacks, the scanner check, ``cancel`` and the raw folder work as they do in
    ``run_session``: stages CHECKING (and WAITING), SCANNING, PROCESSING (not after a cancel or
    a scanner failure) and DONE, the same cancel rules (a cancel during the scan makes no PDF
    and keeps the pages scanned so far; a cancel while the PDF or its searchable text is made
    publishes nothing), the same ``OSError`` before anything is scanned when the raw folder
    cannot be made, and no ``Exception`` after that: it comes back in the result's ``error``
    once the raw pages are settled. Something that is no ``Exception`` propagates, after the
    raw pages are moved to ``.raw/<stamp>/``. The raw folder is owner-only (mode 0700).

    The settings are checked first, before the raw folder is made or the scanner is touched
    (a scan of a stack of paper is not started for a PDF that cannot be made): a
    ``DocumentSettingsError`` for a name with no usable characters, OCR languages that are no
    Tesseract codes or an output folder that is not an existing folder, an ``OcrMissingError``
    when searchable text is required (``OcrMode.ON``) and ``ocrmypdf`` is not installed. Both
    are ``DocumentError`` with a message fit to show as it is.

    A scanner that fails part-way leaves the pages it finished and **no PDF is made from part
    of a stack** (a PDF with its last pages missing is too easy to take for the whole): the
    result carries the error, the pages are kept (``kept_pages``) and ``ffscan doc process``
    can make a PDF from them. A page the scanned file does not give a resolution for is taken
    at ``request.dpi``, the resolution that was asked for. ``scan`` and ``build`` replace
    ``run_scan`` and ``build_document`` (for tests, or a front end that must wrap them).
    """
    hooks = _Hooks(
        scan=run_scan if scan is None else scan,
        precheck=precheck,
        on_page=on_page,
        on_stage=on_stage,
        cancel=cancel,
        build=build_document if build is None else build,
    )
    _refuse_unusable(request)
    raw = create_raw_dir(request.raw_root, keep=request.raw_policy is RawPolicy.KEEP, private=True)
    try:
        outcome = _work(request, raw, hooks)
    except BaseException as abort:  # not an Exception: it cannot come back as a result
        keep_after_abort(raw, request.raw_root, abort, settle_raw_dir)
        raise
    return announce_done(_settle(request, raw, outcome), hooks)


def _refuse_unusable(request: DocumentScanRequest) -> None:
    """Raise if the PDF could not be made, before the raw folder, the scanner or its check."""
    check_settings(request.settings)
    output_root = request.settings.output_root
    if not output_root.is_dir():
        raise DocumentSettingsError(f"the output folder {output_root} is not an existing folder")


def _work(request: DocumentScanRequest, raw: Path, hooks: _Hooks) -> _Outcome:
    """Scan into ``raw`` and make the PDF; never raises an ``Exception``."""
    pages: tuple[Path, ...] = ()
    try:
        scanned = scan_pages(request, raw, hooks, check_scanner)
        pages = scanned.pages
        if scanned.cancelled:
            return _Outcome(pages, cancelled=True)
        if scanned.error is not None:  # the scanner stopped part-way: no PDF of part of a stack
            logger.error(
                "the scan stopped early, after %d finished pages; "
                "no PDF is made from part of a stack",
                len(pages),
            )
            return _Outcome(pages, error=scanned.error)
        hooks.stage(Stage.PROCESSING)
        settings = replace(request.settings, fallback_dpi=request.dpi)
        document = hooks.build(pages, settings, cancel=hooks.cancel)
    except (KeyboardInterrupt, DocumentCancelledError):  # the front end's signal handler: stop
        logger.debug("the session was stopped", exc_info=True)
        return _Outcome(pages, cancelled=True)
    except Exception as error:
        logger.debug("the session ended by an exception", exc_info=True)
        return _Outcome(pages, error=error)
    return _Outcome(pages, document)


def _settle(request: DocumentScanRequest, raw: Path, outcome: _Outcome) -> DocumentSessionResult:
    """Keep or delete the raw pages as the outcome and the policy say, and report it."""
    settled = settle_pages(
        raw,
        request.raw_root,
        reason=_keep_reason(request.raw_policy, outcome),
        not_deleted=DocumentRawReason.NOT_DELETED,
        reported=outcome.pages,
        settle=settle_raw_dir,
        album=request.settings.output_root,
    )
    return DocumentSessionResult(
        document=outcome.document,
        pages_scanned=len(outcome.pages),
        raw_dir=settled.raw_dir,
        raw_reason=settled.reason,
        error=outcome.error,
        cancelled=outcome.cancelled,
        kept_pages=settled.kept_pages,
    )


def _keep_reason(policy: RawPolicy, outcome: _Outcome) -> DocumentRawReason | None:
    """Why the raw pages must stay, or None when they may go: only a clean run lets them go."""
    reason = _failure_reason(outcome)
    return reason if reason is not None else _policy_reason(policy, outcome.document)


def _failure_reason(outcome: _Outcome) -> DocumentRawReason | None:
    """The reason when the run was not clean; a lost page means scanning the stack again."""
    document = outcome.document
    if outcome.cancelled:
        return DocumentRawReason.CANCELLED
    if outcome.error is not None:
        is_scanner = isinstance(outcome.error, ScannerError)
        return DocumentRawReason.SCAN_ERROR if is_scanner else DocumentRawReason.ERROR
    if document is None:  # no result and no known cause: the run ended early, the pages stay
        return DocumentRawReason.ERROR
    return None if document.ok else DocumentRawReason.OCR_FAILED


def _policy_reason(policy: RawPolicy, document: DocumentResult | None) -> DocumentRawReason | None:
    """The reason when the run was clean: asked for, or a blank page was dropped.

    A dropped page keeps the pages too (unless the policy is DISCARD), so that a page with
    faint pencil that was taken for blank is never lost for good.
    """
    if policy is RawPolicy.KEEP:
        return DocumentRawReason.REQUESTED
    if document is not None and document.dropped and policy is not RawPolicy.DISCARD:
        return DocumentRawReason.PAGES_DROPPED
    return None
