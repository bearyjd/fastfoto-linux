"""Turn raw scanner pages into album files: assemble, orient, enhance and write.

``process_pages`` is the one entry point the CLI and the desktop app call. It works one
sheet at a time, so only one sheet is in memory, and one bad sheet never loses the others: its
problem is recorded in the returned ``ProcessResult`` instead of being raised. A failing optional
step (the orienter or an enhancer) costs a sheet only its enhanced copy.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
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
INCOMPLETE_REASON = "incomplete sheet: only one of its two pages was scanned, so a side is missing"


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
    saved: WrittenFiles | None = None


@dataclass(frozen=True)
class ProcessResult:
    """What ``process_pages`` did.

    ``written`` holds one entry per photo that reached disk. ``failed`` lists the sheets that
    were skipped (unreadable page, no photo found, the writer failing); nothing of such a sheet
    is written. ``degraded`` lists written sheets whose orienter or an enhancer failed: they got
    their original (turned only if the orienter worked) but no enhanced copy. ``uncertain``
    lists written photos that need a look: front and back could not be told apart by content
    (they keep their back, whatever the back policy), or only one page of the sheet was
    scanned. ``dropped_backs`` names the back pages the ``AUTO`` policy left out for want of
    writing, so that dropping one is never silent. ``unchanged`` counts the sheets whose
    enhancers left the picture byte-identical: they get no ``_a`` copy. ``cancelled`` is True
    when the caller's cancel event stopped the run before every sheet was handled: what is listed
    is only the part that was done.
    """

    written: tuple[WrittenFiles, ...] = ()
    failed: tuple[SheetIssue, ...] = ()
    uncertain: tuple[SheetIssue, ...] = ()
    degraded: tuple[SheetIssue, ...] = ()
    dropped_backs: tuple[str, ...] = ()
    unchanged: int = 0
    cancelled: bool = False
    sheets: int = 0

    @property
    def photos(self) -> int:
        return len(self.written)

    @property
    def backs_kept(self) -> int:
        return sum(files.back is not None for files in self.written)

    @property
    def enhanced(self) -> int:
        return sum(files.enhanced is not None for files in self.written)

    @property
    def backs_dropped(self) -> int:
        return len(self.dropped_backs)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.degraded and not self.cancelled


@dataclass(frozen=True)
class _Prepared:
    """The images of one sheet after the optional steps; ``degraded`` says which one failed."""

    front: np.ndarray
    enhanced: np.ndarray | None = None
    degraded: str | None = None
    unchanged: bool = False


@dataclass(frozen=True)
class _Handled:
    """What became of one sheet, without the sheet's images (so they can be freed)."""

    files: WrittenFiles | None = None
    failure: str | None = None
    degraded: str | None = None
    unchanged: bool = False
    dropped_back: str | None = None
    uncertain: str | None = None


@dataclass
class _Tally:
    """What ``process_pages`` has found so far; private, updated in place sheet by sheet."""

    paths: tuple[Path, ...]
    duplex: bool
    written: list[WrittenFiles] = field(default_factory=list)
    failed: list[SheetIssue] = field(default_factory=list)
    uncertain: list[SheetIssue] = field(default_factory=list)
    degraded: list[SheetIssue] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    unchanged: int = 0

    def fail(self, sheet: int | None, reason: str) -> None:
        self.failed.append(_sheet_issue(sheet, self.paths, self.duplex, reason))

    def add(self, sheet: int, handled: _Handled) -> WrittenFiles | None:
        """Record what became of one sheet; its files if it was written."""
        if handled.files is None:
            self.fail(sheet, handled.failure or "")
            return None
        self.written.append(handled.files)
        self.unchanged += handled.unchanged
        for reason, issues in (
            (handled.degraded, self.degraded),
            (handled.uncertain, self.uncertain),
        ):
            if reason is not None:
                issues.append(_sheet_issue(sheet, self.paths, self.duplex, reason))
        if handled.dropped_back is not None:
            self.dropped.append(handled.dropped_back)
        return handled.files

    def result(self, *, cancelled: bool) -> ProcessResult:
        return ProcessResult(
            tuple(self.written),
            tuple(self.failed),
            tuple(self.uncertain),
            tuple(self.degraded),
            tuple(self.dropped),
            self.unchanged,
            cancelled,
        )


def process_pages(
    pages: Sequence[Path],
    settings: ProcessSettings,
    *,
    on_photo: Callable[[WrittenFiles], None] | None = None,
    cancel: threading.Event | None = None,
) -> ProcessResult:
    """Process the pages of one scan batch (in scan order) into the album folder.

    Per sheet: crop and pair the sides, turn the front upright, write the original, run the
    enhancers over the oriented front for the ``_a`` copy, and write the back as the back
    policy says. Failures are collected, not raised, so a bad sheet costs only itself;
    ``KeyboardInterrupt`` and the like propagate. If the orienter or an enhancer fails, the
    sheet is still written (without ``_a``) and listed as degraded. An odd page count in a
    duplex batch makes the last page a front without a back (a warning is logged, and the sheet
    is listed as incomplete). The scan time of a photo is the modification time of its page file.
    Raises ``OutputRootMissingError`` before reading anything when the output folder does not
    exist.

    ``on_photo(files)`` is called on the calling thread right after a photo's files are
    written, in order; it should be quick, because the next sheet waits for it. An exception it
    raises propagates (it is not a failed sheet): the run stops there and the photos already
    written stay on disk. ``cancel`` is checked before each sheet is loaded, so a sheet that is
    being processed is finished first; once it is set, the sheets not yet handled are left alone
    and the partial result comes back with ``cancelled`` True (unless nothing was left to do).
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
    total = (len(paths) + 1) // 2 if settings.duplex else len(paths)
    tally = _Tally(paths, settings.duplex)
    batch = iter_photos(
        paths,
        duplex=settings.duplex,
        back_policy=settings.back_policy,
        expect_front_first=settings.expect_front_first,
        allow_odd=True,
        on_sheet_error=lambda error: tally.fail(error.sheet, str(error)),
    )
    done = 0  # the sheets up to this number are settled: written, failed or skipped
    while not (cancelled := _cancelled_early(cancel, done, total)):
        photo = next(batch, None)
        if photo is None:
            break
        done = photo.index + 1
        handled = _handle(photo, settings)
        del photo  # the next sheet is loaded while this loop waits; do not hold the last one
        files = tally.add(done, handled)
        if files is None:
            continue
        logger.info("sheet %d/%d: wrote %s", done, total, ", ".join(p.name for p in files.paths))
        if on_photo is not None:
            on_photo(files)
    return tally.result(cancelled=cancelled)


def _cancelled_early(cancel: threading.Event | None, done: int, total: int) -> bool:
    """Whether ``cancel`` is set while sheets are still waiting to be handled."""
    return cancel is not None and cancel.is_set() and done < total


def _handle(photo: Photo, settings: ProcessSettings) -> _Handled:
    """Write one sheet; a failure of the writer (or anything unforeseen) costs this sheet only."""
    sheet = photo.index + 1
    try:
        prepared = _prepare(photo, settings)
        files = _write(photo, prepared, settings)
    except Exception as error:  # any writer failure costs this sheet only
        reason = _reason(error)
        logger.error("sheet %d: %s", sheet, reason)
        return _Handled(failure=reason)
    if prepared.degraded is not None:
        logger.error("sheet %d: %s; wrote the original only", sheet, prepared.degraded)
    return _Handled(
        files=files,
        degraded=prepared.degraded,
        unchanged=prepared.unchanged,
        dropped_back=_dropped_back(photo, settings),
        uncertain=_uncertain_reason(photo, settings),
    )


def _dropped_back(photo: Photo, settings: ProcessSettings) -> str | None:
    """The back page the AUTO policy left out for want of writing (a kept back is not dropped)."""
    has_back_page = len(photo.source_pages) > 1
    if settings.back_policy is BackPolicy.AUTO and has_back_page and photo.back is None:
        return photo.source_pages[1].name
    return None


def _uncertain_reason(photo: Photo, settings: ProcessSettings) -> str | None:
    if settings.duplex and len(photo.source_pages) == 1:  # the other side was never scanned
        return INCOMPLETE_REASON
    return UNCERTAIN_REASON if photo.side_uncertain else None


def _prepare(photo: Photo, settings: ProcessSettings) -> _Prepared:
    """Turn the front upright and run the enhancers; a failing step only forfeits the ``_a`` copy.

    With a failed orienter the original stays as scanned and no enhancer runs (an enhanced copy
    of a sideways photo would only disagree with it).
    """
    front = photo.front
    if settings.orienter is not None:
        try:
            front = settings.orienter(front, photo.dpi)
        except Exception as error:  # an optional step: the original is still worth writing
            return _Prepared(photo.front, degraded=f"orienter failed: {_reason(error)}")
    if not settings.enhancers:
        return _Prepared(front)
    enhanced = front
    try:
        for enhancer in settings.enhancers:
            enhanced = enhancer(enhanced, photo.dpi)
    except Exception as error:  # an optional step: the original is still worth writing
        return _Prepared(front, degraded=f"enhancer failed: {_reason(error)}")
    if enhanced.dtype == front.dtype and np.array_equal(enhanced, front):
        return _Prepared(front, unchanged=True)
    return _Prepared(front, enhanced)


def _write(photo: Photo, prepared: _Prepared, settings: ProcessSettings) -> WrittenFiles:
    return write_photo(
        prepared.front,
        dpi=photo.dpi,
        output_root=settings.output_root,
        back=photo.back,
        enhanced=prepared.enhanced,
        album=settings.album,
        prefix=settings.prefix,
        date=settings.date,
        notes=settings.notes,
        scanned_at=_scanned_at(photo),
        quality=settings.quality,
        keep_original=settings.keep_original,
    )


def _scanned_at(photo: Photo) -> datetime | None:
    """When the photo's front page file was written: the scan time, as the file system knows it.

    None (the writer then uses the current time) when the file cannot be inspected.
    """
    try:
        return datetime.fromtimestamp(photo.source_pages[0].stat().st_mtime)
    except OSError as error:
        logger.debug("cannot read the time of %s: %s", photo.source_pages[0].name, error)
        return None


def _reason(error: Exception) -> str:
    return str(error) or type(error).__name__


def _sheet_issue(
    sheet: int | None, paths: tuple[Path, ...], duplex: bool, reason: str
) -> SheetIssue:
    """An issue for sheet number ``sheet`` (1-based), naming its pages in scan order."""
    if sheet is None:
        return SheetIssue(None, (), reason)
    first = 2 * (sheet - 1) if duplex else sheet - 1
    names = tuple(p.name for p in paths[first : first + (2 if duplex else 1)])
    return SheetIssue(sheet, names, reason)
