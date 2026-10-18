"""Explicit, cancellable downloads of fixed official, pinned OCR model objects.

TLS authenticates the official endpoint; exact size and Git blob identity bind each model to
our packaged catalogue. Downloads use a private opener which never follows redirects, unique
private temporary files, and atomic publication. No OCR operation calls this module implicitly.
"""

import contextlib
import os
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import BinaryIO, cast

from fastfoto_linux.documents import ocr_languages as models

DOWNLOAD_TIMEOUT_S = 15.0
DOWNLOAD_DEADLINE_S = 120.0
DOWNLOAD_CHUNK_BYTES = 64 * 1024
MODEL_BASE_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        raise OSError("OCR download redirect refused; use the pinned official URL")


def _open_url(url: str, *, timeout: float) -> BinaryIO:
    opener = urllib.request.build_opener(_NoRedirect())
    return cast(BinaryIO, opener.open(url, timeout=timeout))


def _check_time(deadline: float, cancel: threading.Event | None) -> None:
    models._cancelled(cancel)
    if time.monotonic() >= deadline:
        raise OSError("OCR model download exceeded its time limit")


def _transfer(  # noqa: PLR0913, PLR0917
    url: str,
    target: Path,
    model: models._Model,
    cancel: threading.Event | None,
    progress: Callable[[str, int, int], None] | None,
    deadline: float,
) -> None:
    received = 0
    _check_time(deadline, cancel)
    with contextlib.closing(_open_url(url, timeout=DOWNLOAD_TIMEOUT_S)) as response:
        if response.geturl() != url:
            raise OSError("OCR download URL changed; redirects are refused")
        descriptor = os.open(target, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "wb") as output:
            while True:
                _check_time(deadline, cancel)
                read = getattr(response, "read1", response.read)
                chunk = read(min(DOWNLOAD_CHUNK_BYTES, model.size - received + 1))
                _check_time(deadline, cancel)
                if not chunk:
                    break
                received += len(chunk)
                if received > model.size or received > models.MAX_MODEL_BYTES:
                    raise OSError("OCR model size exceeds its verified catalogue size")
                output.write(chunk)
                if progress is not None:
                    progress(model.code, received, model.size)
            output.flush()
            os.fsync(output.fileno())
    _check_time(deadline, cancel)
    if models._verified_bytes(target, model) is None:
        raise OSError("OCR model integrity verification failed (size or Git blob identity)")


def _download_one(
    catalog: models._Catalog,
    model: models._Model,
    root: Path,
    cancel: threading.Event | None,
    progress: Callable[[str, int, int], None] | None,
) -> None:
    destination = root / f"{model.code}.traineddata"
    if models._verified_bytes(destination, model) is not None:
        if progress is not None:
            progress(model.code, model.size, model.size)
        return
    descriptor, name = tempfile.mkstemp(prefix=".model-", dir=root)
    os.close(descriptor)
    temporary = Path(name)
    try:
        url = f"{MODEL_BASE_URL}/{catalog.revision}/{model.code}.traineddata"
        deadline = time.monotonic() + DOWNLOAD_DEADLINE_S
        _transfer(url, temporary, model, cancel, progress, deadline)
        _check_time(deadline, cancel)
        models._cache_root(catalog)  # recheck before publishing into the managed namespace
        os.replace(temporary, destination)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def download_languages(
    codes: Sequence[str],
    *,
    cancel: threading.Event | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> None:
    """Download exactly the requested catalogue codes, without accepting paths or user URLs."""
    models._cancelled(cancel)
    catalog = models._catalog()
    known = catalog.models
    requested = tuple(dict.fromkeys(codes))
    if any(code not in known for code in requested):
        raise ValueError("Unknown OCR language code; choose a language from the catalogue")
    if not requested:
        return
    root = models._cache_root(catalog, create=True)
    for code in requested:
        models._cancelled(cancel)
        _download_one(catalog, known[code], root, cancel, progress)
