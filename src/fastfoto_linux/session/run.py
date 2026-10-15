"""Run one scan session."""

import threading
from collections.abc import Callable

from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import process_pages  # noqa: F401
from fastfoto_linux.scanner import run_scan  # noqa: F401
from fastfoto_linux.session.request import ScanRequest
from fastfoto_linux.session.result import SessionResult, Stage


def run_session(  # noqa: PLR0913
    request: ScanRequest,
    *,
    on_page: Callable[[int], None] | None = None,
    on_photo: Callable[[WrittenFiles], None] | None = None,
    on_stage: Callable[[Stage], None] | None = None,
    cancel: threading.Event | None = None,
    scan: Callable[..., object] | None = None,
    process: Callable[..., object] | None = None,
) -> SessionResult:
    """Stub."""
    raise NotImplementedError
