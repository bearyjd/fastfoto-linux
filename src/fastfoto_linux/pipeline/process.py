"""Turn raw scanner pages into album files: assemble, orient, enhance and write.

``process_pages`` is the one entry point the CLI (and later the desktop app) calls. It works one
sheet at a time, so only one sheet is in memory, and one bad sheet never loses the others: its
problem is recorded in the returned ``ProcessResult`` instead of being raised.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from fastfoto_linux.output import (
    DEFAULT_QUALITY,
    DateRange,
    OutputRootMissingError,
    PhotoDate,
    WrittenFiles,
    write_photo,
)
from fastfoto_linux.output.errors import InvalidNotesError
from fastfoto_linux.output.metadata import MAX_NOTES_CHARS
from fastfoto_linux.output.naming import sanitise_album, sanitise_prefix
from fastfoto_linux.output.writer import MAX_QUALITY, MIN_QUALITY
from fastfoto_linux.pipeline.sides import BackPolicy, Photo, iter_photos

logger = logging.getLogger(__name__)

Enhancer = Callable[[np.ndarray, int], np.ndarray]
"""``(image, dpi) -> new image``; must not modify its input (it is also what gets written)."""
Orienter = Callable[[np.ndarray, int], np.ndarray]
"""``(front, dpi) -> upright front``; same contract as :data:`Enhancer`."""

UNCERTAIN_REASON = "front and back could not be told apart by content; the back was kept"


@dataclass(frozen=True)
class ProcessSettings:
    """Everything ``process_pages`` needs besides the pages; validated on construction.

    ``prefix`` None names files after the album (``FastFoto`` without one). ``duplex`` says
    whether pages come in front/back pairs; ``expect_front_first`` is the loading order
    (False: the back is scanned first, as with FastFoto's face-down loading; None: unknown).
    ``orienter`` turns the front only (the back stays as scanned). ``enhancers`` run in order on
    the oriented front and produce the ``_a`` copy; with ``keep_original`` False the plain
    original is then left out.
    """

    output_root: Path
    album: str | None = None
    prefix: str | None = None
    date: PhotoDate | DateRange | None = None
    notes: str | None = None
    duplex: bool = True
    back_policy: BackPolicy = BackPolicy.AUTO
    expect_front_first: bool | None = None
    quality: int = DEFAULT_QUALITY
    keep_original: bool = True
    enhancers: tuple[Enhancer, ...] = ()
    orienter: Orienter | None = None

    def __post_init__(self) -> None:
        if self.album is not None:
            sanitise_album(self.album)
        if self.prefix is not None:
            sanitise_prefix(self.prefix)
        if self.notes is not None and len(self.notes) > MAX_NOTES_CHARS:
            raise InvalidNotesError(
                f"notes are {len(self.notes)} characters long; the limit is {MAX_NOTES_CHARS}"
            )
        if not MIN_QUALITY <= self.quality <= MAX_QUALITY:
            raise ValueError(f"quality must be {MIN_QUALITY}-{MAX_QUALITY}, got {self.quality}")


@dataclass(frozen=True)
class SheetIssue:
    """A sheet worth telling the user about: ``sheet`` is 1-based, ``pages`` are file names."""

    sheet: int | None
    pages: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ProcessResult:
    """What ``process_pages`` did.

    ``written`` holds one entry per photo that reached disk. ``failed`` lists the sheets that
    were skipped (unreadable page, no photo found, an enhancer or the writer failing); nothing
    of such a sheet is written. ``uncertain`` lists written photos whose front and back could
    not be told apart by content: they keep their back, whatever the back policy.
    """

    written: tuple[WrittenFiles, ...] = ()
    failed: tuple[SheetIssue, ...] = ()
    uncertain: tuple[SheetIssue, ...] = ()

    @property
    def photos(self) -> int:
        return len(self.written)

    @property
    def backs_kept(self) -> int:
        return sum(files.back is not None for files in self.written)

    @property
    def enhanced(self) -> int:
        return sum(files.enhanced is not None for files in self.written)


def process_pages(pages: Sequence[Path], settings: ProcessSettings) -> ProcessResult:
    """Process the pages of one scan batch (in scan order) into the album folder.

    Per sheet: crop and pair the sides, turn the front upright, write the original, run the
    enhancers over the oriented front for the ``_a`` copy, and write the back as the back
    policy says. Failures are collected, not raised, so a bad sheet costs only itself;
    ``KeyboardInterrupt`` and the like propagate. An odd page count in a duplex batch makes the
    last page a front without a back (a warning is logged). Raises ``OutputRootMissingError``
    before reading anything when the output folder does not exist.
    """
    paths = tuple(pages)
    if not settings.output_root.is_dir():
        raise OutputRootMissingError(
            f"output folder {settings.output_root} does not exist; create or mount it first"
        )
    if settings.duplex and len(paths) % 2:
        logger.warning(
            "odd number of pages (%d) in a duplex batch; the last is a front", len(paths)
        )
    failed: list[SheetIssue] = []
    written: list[WrittenFiles] = []
    uncertain: list[SheetIssue] = []
    total = (len(paths) + 1) // 2 if settings.duplex else len(paths)
    batch = iter_photos(
        paths,
        duplex=settings.duplex,
        back_policy=settings.back_policy,
        expect_front_first=settings.expect_front_first,
        allow_odd=True,
        on_sheet_error=lambda error: failed.append(
            _sheet_issue(error.sheet, paths, settings.duplex, str(error))
        ),
    )
    for photo in batch:
        try:
            files = _write(photo, settings)
        except Exception as error:  # any enhancer or writer failure costs this sheet only
            reason = str(error) or type(error).__name__
            logger.error("sheet %d: %s", photo.index + 1, reason)
            failed.append(_sheet_issue(photo.index + 1, paths, settings.duplex, reason))
            continue
        logger.info(
            "sheet %d/%d: wrote %s", photo.index + 1, total, ", ".join(p.name for p in files.paths)
        )
        written.append(files)
        if photo.side_uncertain:
            uncertain.append(
                _sheet_issue(photo.index + 1, paths, settings.duplex, UNCERTAIN_REASON)
            )
    return ProcessResult(tuple(written), tuple(failed), tuple(uncertain))


def _write(photo: Photo, settings: ProcessSettings) -> WrittenFiles:
    front = photo.front
    if settings.orienter is not None:
        front = settings.orienter(front, photo.dpi)
    enhanced = None
    if settings.enhancers:
        enhanced = front
        for enhancer in settings.enhancers:
            enhanced = enhancer(enhanced, photo.dpi)
    return write_photo(
        front,
        dpi=photo.dpi,
        output_root=settings.output_root,
        back=photo.back,
        enhanced=enhanced,
        album=settings.album,
        prefix=settings.prefix,
        date=settings.date,
        notes=settings.notes,
        quality=settings.quality,
        keep_original=settings.keep_original,
    )


def _sheet_issue(
    sheet: int | None, paths: tuple[Path, ...], duplex: bool, reason: str
) -> SheetIssue:
    """An issue for sheet number ``sheet`` (1-based), naming its pages in scan order."""
    if sheet is None:
        return SheetIssue(None, (), reason)
    first = 2 * (sheet - 1) if duplex else sheet - 1
    names = tuple(p.name for p in paths[first : first + (2 if duplex else 1)])
    return SheetIssue(sheet, names, reason)
