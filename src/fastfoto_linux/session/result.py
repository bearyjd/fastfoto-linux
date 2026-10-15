"""What a scan session reports back."""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from fastfoto_linux.pipeline.process import ProcessResult


class Stage(Enum):
    """Where a session is, for a progress display."""

    SCANNING = auto()
    PROCESSING = auto()
    DONE = auto()  # the raw pages are settled and the result is about to be returned


class RawReason(Enum):
    """Why the raw pages are still on disk after a session (the first that applies)."""

    CANCELLED = auto()  # the scan or the processing was cancelled or interrupted
    SCAN_ERROR = auto()  # the scanner failed
    ERROR = auto()  # anything else went wrong (processing crashed, a callback raised)
    SHEETS_FAILED = auto()  # a sheet could not be processed
    SHEETS_DEGRADED = auto()  # a sheet was written without its enhanced copy
    REQUESTED = auto()  # the raw policy is KEEP
    BACK_DROPPED = auto()  # a back with no writing was dropped (policy AUTO)
    NOT_DELETED = auto()  # nothing asked for them, but they could not be deleted


@dataclass(frozen=True)
class SessionResult:
    """How a session ended.

    ``process`` is None when nothing was processed (the scan was cancelled or failed without
    leaving pages). ``pages_scanned`` counts the pages the scanner delivered, 0 when the scan
    ended by an exception that did not say. ``raw_dir`` is where the raw pages are now, None
    when they were deleted (or there were none), and ``raw_reason`` says why they stay: both
    are set, or neither. ``error`` is what stopped the session early: a scanner failure (the
    pages scanned before it were still processed), or any other exception, which is handed back
    and not raised so that the raw pages are settled first. ``cancelled`` is True after a
    cancel or an interrupt.
    """

    process: ProcessResult | None = None
    pages_scanned: int = 0
    raw_dir: Path | None = None
    raw_reason: RawReason | None = None
    error: Exception | None = None
    cancelled: bool = False
    kept_pages: tuple[Path, ...] = ()

    @property
    def ok(self) -> bool:
        """True when everything was scanned and processed without a problem."""
        return (
            self.error is None
            and not self.cancelled
            and self.process is not None
            and self.process.ok
        )
