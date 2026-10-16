"""Write scanned photos to album folders as JPEG with EXIF and XMP metadata."""

import io
import operator
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.output.errors import (
    InvalidImageError,
    OutputCollisionError,
    OutputRootMissingError,
)
from fastfoto_linux.output.files import locked_folder, write_new_files
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
    unprocessed_paths,
)

DEFAULT_QUALITY = 95
MAX_DPI = 4800
MAX_INDEX_ATTEMPTS = 5
MIN_QUALITY = 1
MAX_QUALITY = 100
RGB_CHANNELS = 3
CHROMA_444 = 0  # Pillow's subsampling value for 4:4:4 (no chroma subsampling)


def _now() -> datetime:
    """Local write time; a module function so tests can pin it."""
    return datetime.now()


@dataclass(frozen=True)
class WrittenFiles:
    """The files one ``write_photo`` call created; a path is None when not written.

    ``unprocessed_reason`` is set (in words) when the files are the whole pages of a sheet that
    could not be turned into a photo: ``original`` and ``back`` are then those pages.
    """

    directory: Path
    index: int
    original: Path | None
    enhanced: Path | None
    back: Path | None
    unprocessed_reason: str | None = None

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


def _as_int(name: str, value: object) -> int:
    """``value`` as a plain int; accepts numpy integers, rejects bools, floats and strings."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    try:
        return operator.index(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _check_options(dpi: object, quality: object) -> tuple[int, int]:
    dpi_value = _as_int("dpi", dpi)
    if not 1 <= dpi_value <= MAX_DPI:
        raise ValueError(f"dpi must be 1-{MAX_DPI}, got {dpi_value}")
    quality_value = _as_int("quality", quality)
    if not MIN_QUALITY <= quality_value <= MAX_QUALITY:
        raise ValueError(f"quality must be {MIN_QUALITY}-{MAX_QUALITY}, got {quality_value}")
    return dpi_value, quality_value


def _require_root(output_root: Path) -> None:
    """The root is never created: a missing one usually means an unmounted drive or a typo.

    An empty mount point left behind by an unmounted drive does exist, so it passes this check
    and photos would land on the disk underneath; only the caller can tell the difference.
    """
    if not output_root.is_dir():
        raise OutputRootMissingError(
            f"output folder {output_root} does not exist; create or mount it first"
        )


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


def _publish_photo(
    directory: Path,
    file_prefix: str,
    blobs: tuple[bytes | None, bytes | None, bytes | None],
    *,
    unprocessed: bool = False,
) -> WrittenFiles:
    """Number the photo and publish its files; the caller holds the folder lock.

    ``blobs`` are the original, enhanced and back files; with ``unprocessed`` the original and
    the back are named as whole pages (``_unprocessed``, ``_unprocessed_b``).

    If another writer that does not take the lock got there first, a file collides, nothing is
    written, and the next number is tried, up to MAX_INDEX_ATTEMPTS times. That only protects
    against overwriting the same file: a writer that ignores the lock can still reuse a number
    for different files (say, one writes only the original and the other only ``_a``).
    """
    index = 0
    collision: OutputCollisionError | None = None
    for _ in range(MAX_INDEX_ATTEMPTS):
        index = max(next_index(directory, file_prefix), index + 1)
        paths = photo_paths(directory, file_prefix, index)
        targets = (paths.original, paths.enhanced, paths.back)
        if unprocessed:
            whole_front, whole_back = unprocessed_paths(directory, file_prefix, index)
            targets = (whole_front, paths.enhanced, whole_back)
        pairs = list(zip(targets, blobs, strict=True))
        try:
            write_new_files([(path, blob) for path, blob in pairs if blob is not None])
        except OutputCollisionError as exc:
            collision = exc
            continue
        original, enhanced, back = (path if blob is not None else None for path, blob in pairs)
        return WrittenFiles(directory, index, original, enhanced, back)
    raise OutputCollisionError(
        f"no free number for {file_prefix!r} in {directory} after {MAX_INDEX_ATTEMPTS} attempts"
    ) from collision


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

    ``output_root`` must already exist (OutputRootMissingError otherwise; note that an empty
    mount point of an unmounted drive exists too); the album folder is created on demand.
    Writers sharing a folder take turns through a lock file there (OutputLockTimeoutError if
    another writer holds it for too long). All files of the photo are written or none are: an
    existing file raises OutputCollisionError and anything already written by this call is
    removed again. An OSError with EIO from the final folder sync means the files are in place
    but may not be durable. Names are not adapted to the reserved characters of FAT/exFAT
    (``<>:"|?*``), which such a drive would refuse.
    """
    return _write(
        front,
        dpi=dpi,
        output_root=output_root,
        back=back,
        enhanced=enhanced,
        album=album,
        prefix=prefix,
        date=date,
        notes=notes,
        scanned_at=scanned_at,
        quality=quality,
        keep_original=keep_original,
    )


def _write(  # noqa: PLR0913
    front: np.ndarray,
    *,
    dpi: int,
    output_root: Path,
    back: np.ndarray | None,
    enhanced: np.ndarray | None,
    album: str | None,
    prefix: str | None,
    date: PhotoDate | DateRange | None,
    notes: str | None,
    scanned_at: datetime | None,
    quality: int,
    keep_original: bool,
    unprocessed: bool = False,
) -> WrittenFiles:
    """What ``write_photo`` and ``write_unprocessed`` share: check, encode, number and publish."""
    _check_image("front", front)
    for name, array in (("back", back), ("enhanced", enhanced)):
        if array is not None:
            _check_image(name, array)
    dpi, quality = _check_options(dpi, quality)
    directory = album_dir(output_root, album)
    file_prefix = sanitise_prefix(prefix) if prefix is not None else default_prefix(album)
    _require_root(output_root)
    written_at = _now()
    meta = PhotoMetadata(
        scanned_at=scanned_at or written_at,
        written_at=written_at,
        album=sanitise_album(album) if album is not None else None,
        notes=notes,
        date=date,
    )
    exif, xmp = build_exif(meta), build_xmp(meta)
    keep_front = keep_original or enhanced is None

    def encode(array: np.ndarray | None) -> bytes | None:
        if array is None:
            return None
        return _encode_jpeg(array, dpi=dpi, quality=quality, exif=exif, xmp=xmp)

    blobs = (encode(front if keep_front else None), encode(enhanced), encode(back))
    directory.mkdir(exist_ok=True)
    with locked_folder(directory):
        return _publish_photo(directory, file_prefix, blobs, unprocessed=unprocessed)


def write_unprocessed(  # noqa: PLR0913
    front: np.ndarray,
    *,
    dpi: int,
    output_root: Path,
    reason: str,
    back: np.ndarray | None = None,
    album: str | None = None,
    prefix: str | None = None,
    date: PhotoDate | DateRange | None = None,
    notes: str | None = None,
    scanned_at: datetime | None = None,
    quality: int = DEFAULT_QUALITY,
) -> WrittenFiles:
    """Write the whole pages of a sheet that could not be turned into a photo.

    Like :func:`write_photo` (same folder, numbering, locking, JPEG settings and metadata), but
    ``front`` is written as ``<prefix>_NNNN_unprocessed.jpg`` and ``back``, when given, as
    ``<prefix>_NNNN_unprocessed_b.jpg`` (it ends in ``_b``, so tools that look for backs find
    it). ``reason`` says in words why the sheet is not a photo; it comes back as
    ``WrittenFiles.unprocessed_reason``. The sheet takes the next number, so it keeps its place
    in the sequence.
    """
    if not reason:
        raise ValueError("reason must say why the sheet was not processed")
    files = _write(
        front,
        dpi=dpi,
        output_root=output_root,
        back=back,
        enhanced=None,
        album=album,
        prefix=prefix,
        date=date,
        notes=notes,
        scanned_at=scanned_at,
        quality=quality,
        keep_original=True,
        unprocessed=True,
    )
    return replace(files, unprocessed_reason=reason)
