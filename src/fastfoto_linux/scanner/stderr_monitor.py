"""Read scanimage's stderr without blocking: split lines, keep a tail, report finished pages."""

import os
import re
import selectors
from collections import deque
from collections.abc import Callable
from types import TracebackType

from fastfoto_linux.scanner.job import ScanJob

READ_CHUNK_BYTES = 4096
STDERR_TAIL_LINES = 5
# A stderr line without a newline is capped to its last bytes so it cannot grow without bound.
MAX_PARTIAL_BYTES = 64 * 1024
# The final drain after an exit reads at most this many chunks, in case something keeps writing.
MAX_DRAIN_READS = 256
# SANE_Status values (sane/sane.h) with which scanimage reports a page as done.
_SANE_STATUS_GOOD = 0
_SANE_STATUS_EOF = 5
_PAGE_DONE_STATUSES = frozenset({_SANE_STATUS_GOOD, _SANE_STATUS_EOF})
# Printed by scanimage.c in batch mode, e.g. "Scanned page 3. (scanner status = 0)".
_SCANNED_PAGE = re.compile(r"Scanned page ([0-9]+)\. \(scanner status = ([0-9]+)\)")


class StderrMonitor:
    """Reads the stderr pipe ``fd`` of a scanimage process.

    Uses a selector rather than ``select.select`` (which fails for fds >= 1024). ``read`` and
    ``drain`` never block longer than asked; pages are announced through ``on_progress`` only
    once their file exists, because scanimage prints the line before it renames the ``.part``.
    """

    def __init__(self, job: ScanJob, on_progress: Callable[[int], None] | None, fd: int) -> None:
        self._job = job
        self._on_progress = on_progress
        self._fd = fd
        self._selector = selectors.DefaultSelector()
        self._selector.register(fd, selectors.EVENT_READ)
        self._partial = b""
        self._pending_pages: deque[int] = deque()
        self._tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self.at_eof = False
        self.failure: str | None = None  # the first sane_start/sane_read error scanimage printed

    def __enter__(self) -> "StderrMonitor":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._selector.close()

    @property
    def tail_text(self) -> str:
        """The last stderr lines on one line, empty if scanimage said nothing."""
        return " | ".join(self._tail)

    def read(self, timeout: float) -> None:
        """Wait up to ``timeout`` seconds for stderr data and consume one chunk of it."""
        if not self.at_eof and self._selector.select(timeout):
            self._read_chunk()

    def drain(self) -> None:
        """Consume what is already in the pipe, without waiting."""
        for _ in range(MAX_DRAIN_READS):
            if self.at_eof or not self._selector.select(0):
                return
            self._read_chunk()

    def finish(self) -> None:
        """Handle a last line without a newline, then announce what is already on disk."""
        if self._partial:
            self._take_line(self._partial)
            self._partial = b""
        self.announce_finished_pages()

    def announce_finished_pages(self) -> None:
        """Call ``on_progress`` for finished pages whose file exists, in page order."""
        while self._pending_pages and self._job.page_path(self._pending_pages[0]).is_file():
            page = self._pending_pages.popleft()
            if self._on_progress is not None:
                self._on_progress(page)

    def feed(self, data: bytes) -> None:
        *lines, partial = (self._partial + data).split(b"\n")
        self._partial = partial[-MAX_PARTIAL_BYTES:]
        for raw in lines:
            self._take_line(raw)

    def _read_chunk(self) -> None:
        chunk = os.read(self._fd, READ_CHUNK_BYTES)
        if chunk:
            self.feed(chunk)
        else:  # EOF: every write end of the pipe is closed
            self._selector.unregister(self._fd)
            self.at_eof = True

    def _take_line(self, raw: bytes) -> None:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            return
        self._tail.append(line)
        match = _SCANNED_PAGE.search(line)
        if match and int(match.group(2)) in _PAGE_DONE_STATUSES:
            self._pending_pages.append(int(match.group(1)))
