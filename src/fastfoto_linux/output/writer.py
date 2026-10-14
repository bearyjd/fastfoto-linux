"""Write scanned photos to album folders as JPEG with EXIF and XMP metadata."""

import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.output.errors import InvalidImageError
from fastfoto_linux.output.files import write_new_files
from fastfoto_linux.output.metadata import (
    DateRange,
    PhotoDate,
    PhotoMetadata,
    build_exif,
    build_xmp,
)
from fastfoto_linux.output.naming import (
    album_dir,
    default_prefix,
    next_index,
    photo_paths,
    sanitise_album,
    sanitise_prefix,
)

DEFAULT_QUALITY = 95
MIN_QUALITY = 1
MAX_QUALITY = 100
RGB_CHANNELS = 3
CHROMA_444 = 0  # Pillow's subsampling value for 4:4:4 (no chroma subsampling)


def _now() -> datetime:
    """Local write time; a module function so tests can pin it."""
    return datetime.now()


@dataclass(frozen=True)
class WrittenFiles:
    """The files one ``write_photo`` call created; a path is None when not written."""

    directory: Path
    index: int
    original: Path | None
    enhanced: Path | None
    back: Path | None

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(p for p in (self.original, self.enhanced, self.back) if p is not None)


def _check_image(name: str, array: object) -> None:
    if not isinstance(array, np.ndarray):
        raise InvalidImageError(f"{name} image must be a numpy array, got {type(array).__name__}")
    if (
        array.dtype != np.uint8
        or array.ndim != RGB_CHANNELS
        or array.shape[2] != RGB_CHANNELS
        or 0 in array.shape
    ):
        raise InvalidImageError(
            f"{name} image must be a non-empty HxWx3 uint8 RGB array, "
            f"got shape {array.shape} and dtype {array.dtype}"
        )


def _check_options(dpi: int, quality: int) -> None:
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi < 1:
        raise ValueError(f"dpi must be a positive integer, got {dpi!r}")
    if not isinstance(quality, int) or not MIN_QUALITY <= quality <= MAX_QUALITY:
        raise ValueError(f"quality must be {MIN_QUALITY}-{MAX_QUALITY}, got {quality!r}")


def _encode_jpeg(
    array: np.ndarray | None, *, dpi: int, quality: int, exif: bytes, xmp: bytes
) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(
        buffer,
        "JPEG",
        quality=quality,
        subsampling=CHROMA_444,
        dpi=(dpi, dpi),
        exif=exif,
        xmp=xmp,
    )
    return buffer.getvalue()


def write_photo(  # noqa: PLR0913
    front: np.ndarray,
    *,
    dpi: int,
    output_root: Path,
    back: np.ndarray | None = None,
    enhanced: np.ndarray | None = None,
    album: str | None = None,
    prefix: str | None = None,
    date: PhotoDate | DateRange | None = None,
    notes: str | None = None,
    scanned_at: datetime | None = None,
    quality: int = DEFAULT_QUALITY,
    keep_original: bool = True,
) -> WrittenFiles:
    """Write one photo as JPEG files in ``<output_root>/<album>/``, never overwriting.

    Every image is an ``HxWx3`` uint8 **RGB** array (not OpenCV's BGR); inputs are not modified.
    ``front`` is written as ``<prefix>_NNNN.jpg``, ``enhanced`` as ``_a`` and ``back`` as ``_b``,
    the latter two only when given. With ``keep_original=False`` the plain original is skipped
    when an enhanced copy exists, but is still written when there is none. ``prefix`` defaults to
    the album name (``FastFoto`` with no album) and numbering continues after the highest
    existing number in the folder. ``scanned_at`` (default: now) becomes DateTimeDigitized.

    All files of the photo are written or none are: an existing file raises
    OutputCollisionError and anything already written by this call is removed again.
    """
    _check_image("front", front)
    for name, array in (("back", back), ("enhanced", enhanced)):
        if array is not None:
            _check_image(name, array)
    _check_options(dpi, quality)
    directory = album_dir(output_root, album)
    file_prefix = sanitise_prefix(prefix) if prefix is not None else default_prefix(album)
    written_at = _now()
    meta = PhotoMetadata(
        scanned_at=scanned_at or written_at,
        written_at=written_at,
        album=sanitise_album(album) if album is not None else None,
        notes=notes,
        date=date,
    )
    exif, xmp = build_exif(meta), build_xmp(meta)
    index = next_index(directory, file_prefix)
    paths = photo_paths(directory, file_prefix, index)
    result = WrittenFiles(
        directory=directory,
        index=index,
        original=paths.original if keep_original or enhanced is None else None,
        enhanced=paths.enhanced if enhanced is not None else None,
        back=paths.back if back is not None else None,
    )
    files = [
        (path, _encode_jpeg(array, dpi=dpi, quality=quality, exif=exif, xmp=xmp))
        for path, array in (
            (result.original, front),
            (result.enhanced, enhanced),
            (result.back, back),
        )
        if path is not None and array is not None
    ]
    directory.mkdir(parents=True, exist_ok=True)
    write_new_files(files)
    return result
