"""A scan session: scan the feeder, process the pages and settle the raw pages, UI-neutral."""

from fastfoto_linux.session.request import RawPolicy, ScanRequest
from fastfoto_linux.session.result import RawReason, SessionResult, Stage
from fastfoto_linux.session.run import run_session

__all__ = [
    "RawPolicy",
    "RawReason",
    "ScanRequest",
    "SessionResult",
    "Stage",
    "run_session",
]
