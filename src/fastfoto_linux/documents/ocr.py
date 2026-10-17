"""Add a text layer with ``ocrmypdf``, without ever losing the plain PDF.

``ocrmypdf`` is run as a module of the app's own interpreter when it can import it, else as the
program found by ``ocr_tools``; either way with Homebrew's folder on its PATH, where Tesseract
may be (``ocr_tools.ocr_environment``). Its rasterizer is pdfium, so Ghostscript is never used.

The PDF is staged in a private folder (mode 0700) of the system's temporary directory, never in
the output folder; it is removed on every path except a SIGKILL of ``ffscan`` itself, which can
leave an ``.ffscan-ocr-*`` folder behind that can simply be deleted. ``ocrmypdf`` runs there in
its own session so that it and its children can be stopped together, and the result is checked
before it is trusted. The tool's output is thrown away: recognised text is never read, logged or
printed, and a failure is explained from the exit code alone (``ocr_codes``).
"""

import contextlib
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fastfoto_linux.documents.errors import OcrCancelledError
from fastfoto_linux.documents.ocr_codes import TOOL, describe_exit
from fastfoto_linux.documents.ocr_tools import find_ocrmypdf, ocr_environment  # noqa: F401 - re-exported

logger = logging.getLogger(__name__)

LANGS_PATTERN = r"[a-z_]+(\+[a-z_]+)*"
DEFAULT_LANGS = "eng"
RASTERIZER = "pypdfium"  # the known-defective Ghostscript 10.06 is never used
GRACE_S = 5.0  # SIGTERM to SIGKILL
POLL_S = 0.05
STAGING_PREFIX = ".ffscan-ocr-"
PDF_MAGIC = b"%PDF-"
_LANGS = re.compile(LANGS_PATTERN)


class OcrMode(StrEnum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


class OcrStatus(StrEnum):
    DONE = "done"
    SKIPPED = "skipped"  # --ocr off
    UNAVAILABLE = "unavailable"  # --ocr auto and ocrmypdf or Tesseract is not installed
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
    if not _LANGS.fullmatch(text):
        raise ValueError(
            f"{text!r} is not a list of OCR languages: use Tesseract codes such as eng or eng+deu"
        )
    return text


def _command(executable: str, langs: str, source: Path, target: Path) -> list[str]:
    """The command line; ``executable`` is the running interpreter when ocrmypdf is its module."""
    runner = [executable, "-m", TOOL] if executable == sys.executable else [executable]
    return [
        *runner,
        "--output-type",
        "pdf",
        "--rotate-pages",
        "-l",
        langs,
        "--rasterizer",
        RASTERIZER,
        str(source),
        str(target),
    ]


def _stop(process: subprocess.Popen[bytes], grace_s: float) -> None:
    """Stop ``process`` and everything it started: SIGTERM, then SIGKILL after ``grace_s``."""
    group = process.pid  # start_new_session made it the leader of its own group
    with contextlib.suppress(ProcessLookupError):
        os.killpg(group, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=grace_s)
    with contextlib.suppress(ProcessLookupError):  # a child may have outlived the leader
        os.killpg(group, signal.SIGKILL)
    process.wait()


def _wait(
    process: subprocess.Popen[bytes],
    timeout_s: float,
    grace_s: float,
    cancel: threading.Event | None,
) -> int | None:
    """The exit status, or None when the time ran out. Anything else stops the process first."""
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                return process.wait(timeout=POLL_S)
            except subprocess.TimeoutExpired:
                pass
            if cancel is not None and cancel.is_set():
                raise OcrCancelledError("stopped while adding searchable text")
            if time.monotonic() >= deadline:
                _stop(process, grace_s)
                return None
    except BaseException:
        _stop(process, grace_s)
        raise


def _checked(target: Path, page_count: int) -> bytes | str:
    """The finished PDF's bytes, or the reason it cannot be used."""
    try:
        data = target.read_bytes()
    except FileNotFoundError:
        return "ocrmypdf wrote no output file"
    if not data.startswith(PDF_MAGIC):
        return "ocrmypdf did not produce a PDF"
    import pikepdf  # noqa: PLC0415 - loaded only when a PDF is checked, not at `ffscan` start

    try:
        with pikepdf.open(target) as pdf:
            pages = len(pdf.pages)
    except (pikepdf.PdfError, OSError):
        return "ocrmypdf produced a PDF that cannot be opened"
    if pages != page_count:
        return f"ocrmypdf produced {pages} page(s) from {page_count}"
    return data


def _run(  # noqa: PLR0913
    plain_pdf: bytes,
    *,
    executable: str,
    langs: str,
    page_count: int,
    folder: Path,
    timeout_s: float,
    grace_s: float,
    cancel: threading.Event | None,
) -> OcrOutcome:
    source, target = folder / "plain.pdf", folder / "searchable.pdf"
    source.write_bytes(plain_pdf)
    devnull = subprocess.DEVNULL
    process = subprocess.Popen(  # an argument list, never a shell
        _command(executable, langs, source, target),
        stdin=devnull,
        stdout=devnull,
        stderr=devnull,
        env=ocr_environment(),
        start_new_session=True,
    )
    status = _wait(process, timeout_s, grace_s, cancel)
    if status is None:
        return OcrOutcome(OcrStatus.TIMED_OUT, f"ocrmypdf did not finish within {timeout_s:g} s")
    if status != 0:
        return OcrOutcome(OcrStatus.FAILED, describe_exit(status, langs))
    result = _checked(target, page_count)
    if isinstance(result, str):
        return OcrOutcome(OcrStatus.FAILED, result)
    return OcrOutcome(OcrStatus.DONE, pdf=result)


def run_ocr(  # noqa: PLR0913
    plain_pdf: bytes,
    *,
    executable: str,
    langs: str,
    page_count: int,
    staging_parent: Path | None = None,
    timeout_s: float,
    grace_s: float = GRACE_S,
    cancel: threading.Event | None = None,
) -> OcrOutcome:
    """Run ``ocrmypdf --output-type pdf --rotate-pages -l LANGS --rasterizer pypdfium`` on a
    staging copy of the PDF.

    The copy lives in a new private folder (mode 0700) inside ``staging_parent``, which is the
    system temporary directory unless a caller names another one (the output folder is not a
    place for it). Never raises for an OCR problem: a failure, a timeout or an unusable result
    is reported in the outcome and the caller publishes the plain PDF. Raises OcrCancelledError
    when ``cancel`` is set, and lets KeyboardInterrupt through; in both cases the process group
    is stopped (SIGTERM, then SIGKILL after ``grace_s``) and the staging folder removed.
    Recognised text is never read or logged.
    """
    validate_langs(langs)
    try:
        with tempfile.TemporaryDirectory(prefix=STAGING_PREFIX, dir=staging_parent) as folder:
            return _run(
                plain_pdf,
                executable=executable,
                langs=langs,
                page_count=page_count,
                folder=Path(folder),
                timeout_s=timeout_s,
                grace_s=grace_s,
                cancel=cancel,
            )
    except OSError as error:  # the caller reports the outcome once; this is only for --debug
        logger.debug("could not run %s: %s", TOOL, error)
        return OcrOutcome(OcrStatus.FAILED, f"could not run ocrmypdf: {error.strerror or error}")
