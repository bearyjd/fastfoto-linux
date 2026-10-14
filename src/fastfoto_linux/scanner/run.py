"""Run a scanimage batch job, stream its progress and collect the pages it wrote."""

import contextlib
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import IO, cast

from fastfoto_linux.scanner.errors import (
    NoDocumentsError,
    OutputDirError,
    OutputNotEmptyError,
    ScanCancelledError,
    ScanError,
)
from fastfoto_linux.scanner.job import ScanJob, build_argv
from fastfoto_linux.scanner.stderr_monitor import StderrMonitor

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30 * 60.0
# After SIGTERM scanimage calls sane_cancel(); give it this long before SIGKILL.
TERMINATE_GRACE_S = 10.0
# How often stderr reading wakes up to check the cancel event, the timeout and finished pages.
POLL_INTERVAL_S = 0.1
# SANE_Status value (sane/sane.h); scanimage passes the status straight to exit().
SANE_STATUS_NO_DOCS = 7

PopenFactory = Callable[..., "subprocess.Popen[bytes]"]
ProgressCallback = Callable[[int], None]


@dataclass(frozen=True)
class ScanResult:
    """Pages written by a successful scan, in page order."""

    pages: tuple[Path, ...]


class _Outcome(Enum):
    EXITED = auto()
    TIMED_OUT = auto()
    CANCELLED = auto()


def run_scan(  # noqa: PLR0913
    job: ScanJob,
    *,
    env: Mapping[str, str],
    popen: PopenFactory = subprocess.Popen,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
    scanimage: str = "scanimage",
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> ScanResult:
    """Run ``job`` with scanimage and return the pages it produced.

    ``on_progress(page_number)`` is called in page order, on the thread that called ``run_scan``
    (the one supervising scanimage), once a page is finished and its file exists. It must be
    fast and must not block: scanimage is not watched while it runs, so a slow callback delays
    cancel and timeout handling. An exception from it stops scanimage and propagates. Pages that
    finish while scanimage is being stopped (cancel, timeout) are not announced; they are in
    ``pages`` of the raised error.

    Setting ``cancel`` (from any thread) or exceeding ``timeout_s`` stops scanimage with SIGTERM,
    so it can cancel the scanner cleanly, and SIGKILL only if it does not exit within
    ``TERMINATE_GRACE_S``. scanimage runs in its own session, so a terminal Ctrl-C reaches only
    this process, whose KeyboardInterrupt handling stops scanimage the same way.

    Raises OutputDirError / OutputNotEmptyError before anything is started, NoDocumentsError if
    the feeder was empty, ScanCancelledError after a cancel and ScanError for every other
    failure; the cancel and scan errors carry the pages finished before the failure.
    """
    if cancel is not None and cancel.is_set():
        raise ScanCancelledError("scan cancelled before it started")
    _prepare_output_dir(job)
    proc = _start(popen, build_argv(job, scanimage), env)
    try:
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        stderr_fd = cast("IO[bytes]", proc.stderr).fileno()  # stderr=PIPE was requested
        with proc, StderrMonitor(job, on_progress, stderr_fd) as monitor:
            outcome = _supervise(proc, monitor, deadline, cancel)
    except BaseException:  # incl. an interrupt that lands before the supervision starts
        _stop(proc)  # scanimage runs in its own session: nothing else would stop it
        raise
    pages = _find_pages(job)
    if outcome is _Outcome.CANCELLED:
        raise ScanCancelledError(_with_output("scan cancelled", monitor.tail_text), pages=pages)
    if outcome is _Outcome.TIMED_OUT:
        message = _with_output(f"scanimage timed out after {timeout_s:g} s", monitor.tail_text)
        raise ScanError(message, pages=pages)
    return _interpret(pages, proc.returncode, monitor.tail_text)


def _start(
    popen: PopenFactory, argv: tuple[str, ...], env: Mapping[str, str]
) -> "subprocess.Popen[bytes]":
    try:
        return popen(
            argv,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise ScanError(f"could not start scanimage: {exc}") from exc


def _supervise(
    proc: "subprocess.Popen[bytes]",
    monitor: StderrMonitor,
    deadline: float | None,
    cancel: threading.Event | None,
) -> _Outcome:
    try:
        outcome = _watch(proc, monitor, deadline, cancel)
    except BaseException:  # incl. KeyboardInterrupt and a failing on_progress
        _stop(proc)
        raise
    if outcome is _Outcome.EXITED:
        monitor.finish()
    else:
        _stop(proc)
        monitor.drain()  # what scanimage said while it was stopping
    return outcome


def _watch(
    proc: "subprocess.Popen[bytes]",
    monitor: StderrMonitor,
    deadline: float | None,
    cancel: threading.Event | None,
) -> _Outcome:
    """Pump stderr until the process exits, the cancel event is set or the deadline passes.

    Exit is detected with ``poll()`` and not by stderr EOF: a grandchild that inherited the
    pipe keeps it open after scanimage is gone.
    """
    while True:
        if monitor.at_eof:  # stderr closed; wait for the exit in short slices
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=POLL_INTERVAL_S)
        else:
            monitor.read(POLL_INTERVAL_S)
        monitor.announce_finished_pages()
        if proc.poll() is not None:
            monitor.drain()
            return _Outcome.EXITED
        if cancel is not None and cancel.is_set():
            return _Outcome.CANCELLED
        if deadline is not None and time.monotonic() >= deadline:
            return _Outcome.TIMED_OUT


def _stop(proc: "subprocess.Popen[bytes]") -> None:
    """SIGTERM first (scanimage then cancels the scanner), SIGKILL if it hangs."""
    proc.terminate()
    try:
        proc.wait(timeout=TERMINATE_GRACE_S)
    except subprocess.TimeoutExpired:
        logger.warning("scanimage ignored SIGTERM for %g s; killing it", TERMINATE_GRACE_S)
        proc.kill()
        proc.wait()


def _interpret(pages: tuple[Path, ...], returncode: int, tail: str) -> ScanResult:
    logger.debug("scanimage exited %d with %d page(s)", returncode, len(pages))
    if pages and returncode in (0, SANE_STATUS_NO_DOCS):
        return ScanResult(pages=pages)  # 7 after pages: the feeder emptied, end of the stack
    if returncode == SANE_STATUS_NO_DOCS:
        raise NoDocumentsError("the document feeder is empty; load photos and try again")
    if returncode == 0:
        raise ScanError("scanimage exited successfully but wrote no pages", returncode=0)
    raise ScanError(
        f"scanimage failed (exit status {returncode}): {tail or 'no error output'}",
        returncode=returncode,
        pages=pages,
    )


def _with_output(message: str, tail: str) -> str:
    return f"{message} (scanimage said: {tail})" if tail else message


def _prepare_output_dir(job: ScanJob) -> None:
    directory = job.output_dir
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputDirError(
            f"cannot create output directory {directory}: {exc.strerror or exc}"
        ) from exc
    if not os.access(directory, os.W_OK | os.X_OK):
        raise OutputDirError(f"output directory {directory} is not writable")
    if _find_pages(job):
        raise OutputNotEmptyError(
            f"{directory} already contains {job.file_prefix}-NNNN.png files; "
            "refusing to overwrite them"
        )


def _find_pages(job: ScanJob) -> tuple[Path, ...]:
    """Page files for the job's prefix, ordered by page number (not by file name)."""
    pattern = re.compile(rf"{re.escape(job.file_prefix)}-([0-9]{{4,}})\.png")
    try:
        entries = list(job.output_dir.iterdir())
    except OSError as exc:
        raise OutputDirError(
            f"cannot list output directory {job.output_dir}: {exc.strerror or exc}"
        ) from exc
    numbered = [(int(m.group(1)), p) for p in entries if (m := pattern.fullmatch(p.name))]
    return tuple(path for _, path in sorted(numbered))
