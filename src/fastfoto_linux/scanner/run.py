"""Run a scanimage batch job, stream its progress and collect the pages it wrote."""

import logging
import os
import re
import select
import subprocess
import threading
import time
from collections import deque
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

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30 * 60.0
# After SIGTERM scanimage calls sane_cancel(); give it this long before SIGKILL.
TERMINATE_GRACE_S = 10.0
# How often stderr reading wakes up to check the cancel event, the timeout and finished pages.
POLL_INTERVAL_S = 0.1
READ_CHUNK_BYTES = 4096
STDERR_TAIL_LINES = 5
# SANE_Status values (sane/sane.h); scanimage passes the status straight to exit().
SANE_STATUS_GOOD = 0
SANE_STATUS_EOF = 5
SANE_STATUS_NO_DOCS = 7
_PAGE_DONE_STATUSES = frozenset({SANE_STATUS_GOOD, SANE_STATUS_EOF})
# Printed by scanimage.c in batch mode, e.g. "Scanned page 3. (scanner status = 0)".
_SCANNED_PAGE = re.compile(r"Scanned page ([0-9]+)\. \(scanner status = ([0-9]+)\)")

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

    ``on_progress(page_number)`` is called, in order and from the calling thread, once a page is
    finished and its file exists; an exception from it stops scanimage and propagates. Setting
    ``cancel`` (from any thread) or exceeding ``timeout_s`` stops scanimage with SIGTERM, so it
    can cancel the scanner cleanly, and SIGKILL only if it does not exit within
    ``TERMINATE_GRACE_S``.

    Raises OutputDirError / OutputNotEmptyError before anything is started, NoDocumentsError if
    the feeder was empty, ScanCancelledError after a cancel and ScanError for every other
    failure; the cancel and scan errors carry the pages finished before the failure.
    """
    if cancel is not None and cancel.is_set():
        raise ScanCancelledError("scan cancelled before it started")
    _prepare_output_dir(job)
    try:
        proc = popen(
            build_argv(job, scanimage),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ScanError(f"could not start scanimage: {exc}") from exc
    monitor = _StderrMonitor(job, on_progress)
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    with proc:
        outcome = _supervise(proc, monitor, deadline, cancel)
    pages = _find_pages(job)
    if outcome is _Outcome.CANCELLED:
        raise ScanCancelledError("scan cancelled", pages=pages)
    if outcome is _Outcome.TIMED_OUT:
        raise ScanError(f"scanimage timed out after {timeout_s:g} s", pages=pages)
    monitor.finish()
    return _interpret(pages, proc.returncode, monitor.tail)


class _StderrMonitor:
    """Splits scanimage's stderr into lines, keeps the tail and announces finished pages."""

    def __init__(self, job: ScanJob, on_progress: ProgressCallback | None) -> None:
        self._job = job
        self._on_progress = on_progress
        self._partial = b""
        self._pending_pages: deque[int] = deque()
        self.tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)

    def feed(self, data: bytes) -> None:
        *lines, self._partial = (self._partial + data).split(b"\n")
        for raw in lines:
            self._take_line(raw)

    def finish(self) -> None:
        """Handle a last line that had no newline, then announce what is already on disk."""
        if self._partial:
            self._take_line(self._partial)
            self._partial = b""
        self.announce_finished_pages()

    def announce_finished_pages(self) -> None:
        """Call ``on_progress`` for finished pages whose file exists (renamed after the line)."""
        while self._pending_pages and _page_path(self._job, self._pending_pages[0]).is_file():
            page = self._pending_pages.popleft()
            if self._on_progress is not None:
                self._on_progress(page)

    def _take_line(self, raw: bytes) -> None:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            return
        self.tail.append(line)
        match = _SCANNED_PAGE.search(line)
        if match and int(match.group(2)) in _PAGE_DONE_STATUSES:
            self._pending_pages.append(int(match.group(1)))


def _supervise(
    proc: "subprocess.Popen[bytes]",
    monitor: _StderrMonitor,
    deadline: float | None,
    cancel: threading.Event | None,
) -> _Outcome:
    try:
        outcome = _watch(proc, monitor, deadline, cancel)
    except BaseException:
        _stop(proc)
        raise
    if outcome is not _Outcome.EXITED:
        _stop(proc)
    return outcome


def _watch(
    proc: "subprocess.Popen[bytes]",
    monitor: _StderrMonitor,
    deadline: float | None,
    cancel: threading.Event | None,
) -> _Outcome:
    stderr = cast("IO[bytes]", proc.stderr)  # stderr=PIPE was requested
    while True:
        readable, _, _ = select.select([stderr], [], [], POLL_INTERVAL_S)
        if readable:
            chunk = os.read(stderr.fileno(), READ_CHUNK_BYTES)
            if not chunk:  # EOF: scanimage has closed stderr, i.e. exited
                return _await_exit(proc, deadline)
            monitor.feed(chunk)
        monitor.announce_finished_pages()
        if cancel is not None and cancel.is_set():
            return _Outcome.CANCELLED
        if deadline is not None and time.monotonic() >= deadline:
            return _Outcome.TIMED_OUT


def _await_exit(proc: "subprocess.Popen[bytes]", deadline: float | None) -> _Outcome:
    remaining = None if deadline is None else max(deadline - time.monotonic(), 0.0)
    try:
        proc.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        return _Outcome.TIMED_OUT
    return _Outcome.EXITED


def _stop(proc: "subprocess.Popen[bytes]") -> None:
    """SIGTERM first (scanimage then cancels the scanner), SIGKILL if it hangs."""
    proc.terminate()
    try:
        proc.wait(timeout=TERMINATE_GRACE_S)
    except subprocess.TimeoutExpired:
        logger.warning("scanimage ignored SIGTERM for %g s; killing it", TERMINATE_GRACE_S)
        proc.kill()
        proc.wait()


def _interpret(pages: tuple[Path, ...], returncode: int, tail: deque[str]) -> ScanResult:
    logger.debug("scanimage exited %d with %d page(s)", returncode, len(pages))
    if pages and returncode in (0, SANE_STATUS_NO_DOCS):
        return ScanResult(pages=pages)  # 7 after pages: the feeder emptied, end of the stack
    if returncode == SANE_STATUS_NO_DOCS:
        raise NoDocumentsError("the document feeder is empty; load photos and try again")
    if returncode == 0:
        raise ScanError("scanimage exited successfully but wrote no pages", returncode=0)
    raise ScanError(
        f"scanimage failed (exit status {returncode}): {' | '.join(tail) or 'no error output'}",
        returncode=returncode,
        pages=pages,
    )


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


def _page_path(job: ScanJob, number: int) -> Path:
    return job.output_dir / f"{job.file_prefix}-{number:04d}.png"


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
