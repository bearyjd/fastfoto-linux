"""EXIF and XMP metadata for written photos: dates, notes, album."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

MAX_NOTES_CHARS = 10_000


@dataclass(frozen=True)
class PhotoDate:
    """A photo date with year, year-month or full-day precision."""

    year: int
    month: int | None = None
    day: int | None = None

    @classmethod
    def parse(cls, text: str) -> Self:
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError

    @property
    def exif_datetime(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class DateRange:
    """An inclusive range of photo dates, e.g. a decade."""

    start: PhotoDate
    end: PhotoDate

    @classmethod
    def parse(cls, text: str) -> Self:
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class PhotoMetadata:
    """Everything that goes into one written file's EXIF and XMP."""

    scanned_at: datetime
    written_at: datetime
    album: str | None = None
    notes: str | None = None
    date: PhotoDate | DateRange | None = None


def build_exif(meta: PhotoMetadata) -> bytes:
    raise NotImplementedError


def build_xmp(meta: PhotoMetadata) -> bytes:
    raise NotImplementedError
