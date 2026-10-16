"""Add a text layer with ``ocrmypdf``, without ever losing the plain PDF."""

import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

LANGS_PATTERN = r"[a-z_]+(\+[a-z_]+)*"
DEFAULT_LANGS = "eng"
GRACE_S = 5.0


class OcrMode(StrEnum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


class OcrStatus(StrEnum):
    DONE = "done"
    SKIPPED = "skipped"  # --ocr off
    UNAVAILABLE = "unavailable"  # --ocr auto and ocrmypdf is not installed
    FAILED = "failed"
    TIMED_OUT = "timed out"


@dataclass(frozen=True)
class OcrOutcome:
    """How the OCR step went; ``pdf`` holds the searchable PDF only when ``status`` is DONE."""

    status: OcrStatus
    detail: str = ""
    pdf: bytes | None = None


def validate_langs(text: str) -> str:
    """``text`` if it is Tesseract language codes joined by ``+``, else ValueError."""
    raise NotImplementedError


def find_ocrmypdf() -> str | None:
    """The ``ocrmypdf`` executable on PATH, or None."""
    raise NotImplementedError


def run_ocr(  # noqa: PLR0913
    plain_pdf: bytes,
    *,
    executable: str,
    langs: str,
    page_count: int,
    staging_parent: Path,
    timeout_s: float,
    grace_s: float = GRACE_S,
    cancel: threading.Event | None = None,
) -> OcrOutcome:
    """Run ``ocrmypdf --output-type pdf --rotate-pages -l LANGS`` on a staging copy of the PDF.

    Never raises for an OCR problem: a failure, a timeout or an unusable result is reported in
    the outcome and the caller publishes the plain PDF. Raises OcrCancelledError when ``cancel``
    is set, and lets KeyboardInterrupt through; in both cases the process group is stopped
    (SIGTERM, then SIGKILL after ``grace_s``) and the staging folder removed. Recognised text is
    never read or logged.
    """
    raise NotImplementedError
