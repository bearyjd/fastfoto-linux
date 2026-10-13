"""Run a scanimage batch job and collect the pages it wrote."""

import logging
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.scanner.errors import NoDocumentsError, ScanError
from fastfoto_linux.scanner.job import ScanJob, build_argv

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30 * 60.0
# SANE_Status values scanimage passes straight to exit() (sane/sane.h).
SANE_STATUS_NO_DOCS = 7
STDERR_TAIL_LINES = 5
_NO_DOCS_TEXT = "out of documents"

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ScanResult:
    """Pages written by a successful scan, in page order, and scanimage's exit status."""

    pages: tuple[Path, ...]
    returncode: int


def run_scan(
    job: ScanJob,
    *,
    env: Mapping[str, str],
    runner: Runner = subprocess.run,
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
) -> ScanResult:
    """Run ``job`` with scanimage and return the pages it produced.

    Raises FileExistsError if ``job.output_dir`` already holds pages for this prefix,
    NoDocumentsError if the feeder was empty, and ScanError for any other failure (the pages
    finished before the failure are kept on the exception).
    """
    if _find_pages(job):
        raise FileExistsError(
            f"{job.output_dir} already contains {job.file_prefix}-NNNN.png files; "
            "refusing to overwrite them"
        )
    job.output_dir.mkdir(parents=True, exist_ok=True)
    argv = build_argv(job)
    try:
        completed = runner(
            argv,
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScanError(f"scanimage timed out after {timeout_s} s", pages=_find_pages(job)) from exc
    except OSError as exc:
        raise ScanError(f"could not start scanimage: {exc}") from exc
    return _interpret(job, completed.returncode, completed.stderr or "")


def _interpret(job: ScanJob, returncode: int, stderr: str) -> ScanResult:
    pages = _find_pages(job)
    logger.debug("scanimage exited %d with %d page(s)", returncode, len(pages))
    if returncode == 0 and pages:
        return ScanResult(pages=pages, returncode=returncode)
    if returncode == SANE_STATUS_NO_DOCS and pages:
        return ScanResult(pages=pages, returncode=returncode)  # feeder emptied: end of stack
    if not pages and (returncode == SANE_STATUS_NO_DOCS or _NO_DOCS_TEXT in stderr.lower()):
        raise NoDocumentsError("the document feeder is empty; load photos and try again")
    if returncode == 0:
        raise ScanError("scanimage exited successfully but wrote no pages", returncode=0)
    raise ScanError(
        f"scanimage failed (exit status {returncode}): {_stderr_tail(stderr)}",
        returncode=returncode,
        pages=pages,
    )


def _find_pages(job: ScanJob) -> tuple[Path, ...]:
    """Page files for the job's prefix, ordered by page number (not by file name)."""
    pattern = re.compile(rf"{re.escape(job.file_prefix)}-(\d{{4,}})\.png")
    numbered = [
        (int(match.group(1)), path)
        for path in job.output_dir.glob(f"{job.file_prefix}-*.png")
        if (match := pattern.fullmatch(path.name))
    ]
    return tuple(path for _, path in sorted(numbered))


def _stderr_tail(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return " | ".join(lines[-STDERR_TAIL_LINES:]) or "no error output"
