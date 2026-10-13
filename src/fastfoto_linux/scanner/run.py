"""Run a scanimage batch job and collect the pages it wrote."""

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.scanner.job import ScanJob

DEFAULT_TIMEOUT_S = 30 * 60.0

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ScanResult:
    pages: tuple[Path, ...]
    returncode: int


def run_scan(
    job: ScanJob,
    *,
    env: Mapping[str, str],
    runner: Runner = subprocess.run,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
) -> ScanResult:
    raise NotImplementedError
