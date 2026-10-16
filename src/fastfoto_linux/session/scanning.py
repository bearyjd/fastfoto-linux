"""The parts of a session that scan and settle raw pages: shared by photo and document sessions.

Nothing here prints, reads the command line or installs signal handlers. The functions that
touch the scanner check or the raw folder take them as arguments (``check``, ``settle``), so
that each session looks the real ones up in its own module when it runs, and a test that
replaces ``fastfoto_linux.session.run.check_scanner`` (or the ``documents`` one) replaces
exactly what that session uses.
"""

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Protocol

from fastfoto_linux.scanner import (
    Mode,
    ScanCancelledError,
    ScanError,
    ScanJob,
    ScanResult,
    ScanTarget,
    Source,
)
from fastfoto_linux.scanner.precheck import precheck_applies
from fastfoto_linux.session.raw import is_complete_png, list_pages
from fastfoto_linux.session.result import Stage

logger = logging.getLogger(__name__)

ScanFn = Callable[..., ScanResult]
"""``run_scan``'s call shape: ``(job, *, env, on_progress, cancel) -> ScanResult``."""
PrecheckFn = Callable[..., None]
"""``check_scanner``'s call shape: ``(device, *, cancel)``; raises a ScannerError."""
SettleFn = Callable[..., Path | None]
"""``settle_raw_dir``'s call shape."""


class ScanSpec(Protocol):
    """What a scan request asks the scanner for (a photo request and a document request both do)."""

    @property
    def target(self) -> ScanTarget: ...
    @property
    def dpi(self) -> int: ...
    @property
    def duplex(self) -> bool: ...
    @property
    def mode(self) -> Mode: ...
    @property
    def max_length_mm(self) -> float: ...


@dataclass(frozen=True)
class SessionHooks:
    """The callbacks and collaborators every session has, so they travel as one argument."""

    scan: ScanFn
    precheck: PrecheckFn | None
    on_page: Callable[[int], None] | None
    on_stage: Callable[[Stage], None] | None
    cancel: threading.Event | None

    def stage(self, stage: Stage) -> None:
        if self.on_stage is not None:
            self.on_stage(stage)


@dataclass(frozen=True)
class Scanned:
    """What the scan left: the pages, and why it stopped early if it did."""

    pages: tuple[Path, ...] = ()
    error: ScanError | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class Settlement[R]:
    """Where the raw pages are after a session, and why they are still there."""

    raw_dir: Path | None
    reason: R | None
    kept_pages: tuple[Path, ...]


def build_job(spec: ScanSpec, raw: Path) -> ScanJob:
    """The scanimage job for ``spec``, scanning into ``raw``."""
    return ScanJob(
        device=spec.target.device,
        output_dir=raw,
        source=Source.DUPLEX if spec.duplex else Source.FRONT,
        mode=spec.mode,
        resolution=spec.dpi,
        max_length_mm=spec.max_length_mm,
    )


def scan_pages(spec: ScanSpec, raw: Path, hooks: SessionHooks, check: PrecheckFn) -> Scanned:
    """Check the scanner, then scan into ``raw``. A scanner failure part-way keeps the pages
    finished before it (``Scanned.error``); a failure before any page is raised.

    ``check`` is the scanner check to run unless the caller's ``hooks.precheck`` replaces it.
    """
    job = build_job(spec, raw)
    env = spec.target.env(os.environ)
    try:
        _check_scanner(spec.target.device, hooks, check)
        hooks.stage(Stage.SCANNING)
        result = hooks.scan(job, env=env, on_progress=hooks.on_page, cancel=hooks.cancel)
    except ScanCancelledError as error:
        return Scanned(error.pages, cancelled=True)
    except ScanError as error:
        if not error.pages:
            raise
        logger.error("the scan stopped early, after %d finished pages", len(error.pages))
        return Scanned(error.pages, error=error)
    return Scanned(result.pages)


def _check_scanner(device: str, hooks: SessionHooks, real_check: PrecheckFn) -> None:
    """Make sure a USB scanner answers before scanimage starts, freeing it if a failed send
    jammed it. Without a ``precheck`` of the caller's the real check runs, for a USB scanner
    only and not when ``FF680W_NO_PRECHECK=1``; the CHECKING stage is announced only then, and
    WAITING if the real check runs long."""
    check = hooks.precheck
    if check is None:
        if not precheck_applies(device, os.environ):
            return
        check = partial(real_check, on_slow=lambda: hooks.stage(Stage.WAITING))
    hooks.stage(Stage.CHECKING)
    check(device, cancel=hooks.cancel)


def finished_pages(kept: Path, reported: tuple[Path, ...]) -> tuple[Path, ...]:
    """The pages in ``kept`` the scanner finished: complete PNGs, and only the reported ones
    when the scan reported any (a cancel or a kill can leave the last page cut off mid-write,
    and ``run_scan`` reports every page file it finds)."""
    finished = {page.name for page in reported}
    return tuple(
        page
        for page in list_pages(kept)
        if (not finished or page.name in finished) and is_complete_png(page)
    )


def settle_pages[R](  # noqa: PLR0913 - keyword-only; ``settle`` is the caller's own seam
    raw: Path,
    root: Path,
    *,
    reason: R | None,
    not_deleted: R,
    reported: tuple[Path, ...],
    settle: SettleFn,
    album: Path | None = None,
) -> Settlement[R]:
    """Keep or delete the raw pages as ``reason`` says (None: delete) and report what is left.

    ``not_deleted`` is the reason given when pages nobody asked to keep could not be deleted.
    """
    kept = settle(raw, root, keep=reason is not None, album=album)
    if kept is None:
        return Settlement(None, None, ())
    return Settlement(
        kept, not_deleted if reason is None else reason, finished_pages(kept, reported)
    )


def keep_after_abort(raw: Path, root: Path, abort: BaseException, settle: SettleFn) -> None:
    """Keep the raw pages while ``abort`` is on its way; failing to must not replace it."""
    try:
        kept = settle(raw, root, keep=True)
    except Exception:
        logger.exception("the raw pages in %s could not be settled while aborting", raw)
        return
    if kept is not None:
        logger.error("aborted by %s; the raw pages are kept in %s", type(abort).__name__, kept)


def announce_done[T](result: T, hooks: SessionHooks) -> T:
    """Tell the DONE stage; a callback that raises costs the result nothing."""
    try:
        hooks.stage(Stage.DONE)
    except Exception as error:
        logger.exception("the DONE callback raised; the result is returned anyway")
        earlier = getattr(result, "error", None)
        return replace(result, error=error if earlier is None else earlier)  # type: ignore[type-var]
    return result
