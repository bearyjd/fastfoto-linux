"""Explicit, cancellable downloads of fixed official OCR model objects."""

import threading
from collections.abc import Callable, Sequence


def download_languages(
    codes: Sequence[str],
    *,
    cancel: threading.Event | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> None:
    raise NotImplementedError
