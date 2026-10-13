"""Run a scanimage batch job and collect the pages it wrote."""

import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.scanner.job import ScanJob

DEFAULT_TIMEOUT_S = 30 * 60.0
TERMINATE_GRACE_S = 10.0
POLL_INTERVAL_S = 0.1

PopenFactory = Callable[..., "subprocess.Popen[bytes]"]
ProgressCallback = Callable[[int], None]


@dataclass(frozen=True)
class ScanResult:
    """Pages written by a successful scan, in page order."""

    pages: tuple[Path, ...]


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
    raise NotImplementedError
