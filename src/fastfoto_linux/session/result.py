"""What a scan session reports back."""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from fastfoto_linux.pipeline.process import ProcessResult


class Stage(Enum):
    SCANNING = auto()
    PROCESSING = auto()
    DONE = auto()


class RawReason(Enum):
    REQUESTED = auto()
    SCAN_ERROR = auto()
    ERROR = auto()
    CANCELLED = auto()
    SHEETS_FAILED = auto()
    SHEETS_DEGRADED = auto()
    BACK_DROPPED = auto()
    NOT_DELETED = auto()


@dataclass(frozen=True)
class SessionResult:
    """Stub."""

    process: ProcessResult | None = None
    pages_scanned: int = 0
    raw_dir: Path | None = None
    raw_reason: RawReason | None = None
    error: Exception | None = None
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        raise NotImplementedError
