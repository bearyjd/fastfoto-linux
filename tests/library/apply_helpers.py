"""Shared pieces of the ``fix`` tests: a small library of three photos and its rows."""

from pathlib import Path

from fastfoto_linux.library.plan import PlanRow
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import exif_bytes, make_jpeg, rotate_row

MTIME_NS = 1_100_000_000_123_456_789
FIRST, SECOND, THIRD = "2001/trip_0001_a.jpg", "2001/trip_0002_a.jpg", "b.jpg"


def jpeg(tag: int | None) -> bytes:
    return make_jpeg(load_astronaut(), exif=None if tag is None else exif_bytes(tag, date=True))


def two_rows(lib: Path) -> tuple[PlanRow, PlanRow]:
    return (
        rotate_row(lib, FIRST, 90, 1, 6),
        rotate_row(lib, SECOND, 90, 6, 3),
    )


def statuses(result) -> dict[str, str]:
    return {outcome.path: outcome.status for outcome in result.outcomes}
