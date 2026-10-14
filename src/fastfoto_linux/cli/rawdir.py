"""Stub."""

from pathlib import Path


def utc_stamp() -> str:
    """Stub."""
    raise NotImplementedError


def create_raw_dir(root: Path, *, keep: bool) -> Path:
    """Stub."""
    raise NotImplementedError


def settle_raw_dir(raw: Path, root: Path, *, keep: bool) -> Path | None:
    """Stub."""
    raise NotImplementedError
