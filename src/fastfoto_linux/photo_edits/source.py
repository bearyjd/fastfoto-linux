"""Decode and identify a retained original without rewriting it."""

from pathlib import Path

from fastfoto_linux.photo_edits.model import PhotoSource


def load_source(path: Path, *, expected_sha256: str | None = None) -> PhotoSource:
    """Hash source bytes and normalize EXIF orientation into the canonical pixel space."""
    raise NotImplementedError("photo source loading is pending")
