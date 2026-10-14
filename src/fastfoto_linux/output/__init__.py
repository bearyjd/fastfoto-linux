"""Album output: naming, JPEG writing, EXIF/XMP dates and notes."""

from fastfoto_linux.output.errors import (
    InvalidAlbumError,
    InvalidDateError,
    InvalidImageError,
    InvalidNotesError,
    InvalidPrefixError,
    OutputCollisionError,
    OutputError,
)
from fastfoto_linux.output.metadata import DateRange, PhotoDate
from fastfoto_linux.output.writer import DEFAULT_QUALITY, WrittenFiles, write_photo

__all__ = [
    "DEFAULT_QUALITY",
    "DateRange",
    "InvalidAlbumError",
    "InvalidDateError",
    "InvalidImageError",
    "InvalidNotesError",
    "InvalidPrefixError",
    "OutputCollisionError",
    "OutputError",
    "PhotoDate",
    "WrittenFiles",
    "write_photo",
]
