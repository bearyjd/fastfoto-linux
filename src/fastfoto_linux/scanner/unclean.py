"""A note that our own last scan on a USB address ended abnormally (stub for the red commit)."""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_NAME = "scanner-unclean"


def marker_path() -> Path:
    raise NotImplementedError


def mark(bus: int, address: int, *, now: datetime | None = None) -> None:
    raise NotImplementedError


def is_marked(bus: int, address: int) -> bool:
    raise NotImplementedError


def clear() -> None:
    raise NotImplementedError
