"""Save the whole pages of a sheet that could not be turned into a photo.

The sheet keeps its own number in the sequence, so that no photo of the batch goes missing
unnoticed: its front page is written as ``<prefix>_NNNN_unprocessed.jpg`` and its back as
``<prefix>_NNNN_unprocessed_b.jpg``. Nothing is cut away: the user needs the whole scanner frame
to find the photo, and a long white area costs only file size.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from fastfoto_linux.output import WrittenFiles, write_unprocessed
from fastfoto_linux.pipeline.batch_errors import (
    BatchError,
    NoPhotoOnSheetError,
    PageResolutionError,
    UnreadablePageError,
)
from fastfoto_linux.pipeline.crop import detect_photo
from fastfoto_linux.pipeline.ink import paper_score
from fastfoto_linux.pipeline.io import load_frame, scan_time
from fastfoto_linux.pipeline.side_order import DEFAULT_FRONT_FIRST, decide_sides
from fastfoto_linux.pipeline.sides import BackPolicy

if TYPE_CHECKING:  # process.py imports this module
    from fastfoto_linux.pipeline.process import ProcessSettings

logger = logging.getLogger(__name__)

NO_PHOTO_REASON = "the photo's edges were not found (two items fed together?)"
RESOLUTION_REASON = "the two pages were scanned at different resolutions"
UNREADABLE_REASON = "a page of the sheet could not be read"
GENERIC_REASON = "the photo could not be processed"

Page = tuple[np.ndarray, int]
"""A loaded page: ``(frame, dpi)``."""


def plain_reason(error: BatchError) -> str:
    """Why the sheet is not a photo, in words for the user; the error's own text goes to the log."""
    if isinstance(error, NoPhotoOnSheetError):
        return NO_PHOTO_REASON
    if isinstance(error, PageResolutionError):
        return RESOLUTION_REASON
    if isinstance(error, UnreadablePageError):
        return UNREADABLE_REASON
    logger.debug("%s", error)
    return GENERIC_REASON


def plain_failure_reason(error: Exception) -> str:
    """Why a photo could not be written, in words for the user; the error's own text is dropped.

    A disk or permission problem says what the system said (without the file it names); anything
    else gets the generic sentence. The caller logs the error itself at debug level.
    """
    if isinstance(error, OSError) and error.strerror:
        return f"the photo could not be saved ({error.strerror})"
    return GENERIC_REASON


def save_unprocessed(
    pages: tuple[Path, ...], settings: "ProcessSettings", reason: str
) -> WrittenFiles | None:
    """Write the one or two ``pages`` of a sheet (in feed order) whole; None if that fails.

    The front is chosen like a normal sheet's when both pages show a photo box, else by the feed
    order ``settings`` declares. The back follows the back policy. If only one of two pages can
    be read, that page is saved alone as the side the feed order makes it (a back keeps its ``_b``
    name, whatever the back policy: it is all that is left of the sheet) and the reason says which
    side is missing. Never raises an ``Exception``: pages that cannot be read or files that cannot
    be written leave the sheet as a plain failure, which is the caller's business.
    """
    try:
        return _save(pages, settings, reason)
    except Exception as error:  # the fallback is the plain failure the caller already has
        names = ", ".join(page.name for page in pages)
        # the decoder's or the disk's own words carry absolute paths: debug, not the user's log
        logger.debug(
            "cannot save %s whole: %s", names, str(error) or type(error).__name__, exc_info=True
        )
        return None


@dataclass(frozen=True)
class _Plan:
    """What to write for a sheet: its front and back (either may be missing, never both).

    ``dated_by`` is the page file whose time becomes the scan time; ``reason`` is why the sheet
    is saved whole.
    """

    front: Page | None
    back: Page | None
    dated_by: Path
    reason: str


def _save(pages: tuple[Path, ...], settings: "ProcessSettings", reason: str) -> WrittenFiles:
    plan = _plan(pages, _load_pages(pages), settings, reason)
    main = plan.front or plan.back  # a plan always holds a page
    files = write_unprocessed(
        None if plan.front is None else plan.front[0],
        dpi=main[1],
        output_root=settings.output_root,
        reason=plan.reason,
        back=None if plan.back is None else plan.back[0],
        album=settings.album,
        prefix=settings.prefix,
        date=settings.date,
        notes=settings.notes,
        scanned_at=scan_time(plan.dated_by),
        quality=settings.quality,
    )
    logger.info("saved %s whole: %s", ", ".join(page.name for page in pages), plan.reason)
    return files


def _plan(
    pages: tuple[Path, ...], loaded: list[Page | None], settings: "ProcessSettings", reason: str
) -> _Plan:
    readable = [at for at, page in enumerate(loaded) if page is not None]
    if not readable:
        raise ValueError("no page of the sheet can be read")
    if len(readable) < len(pages):  # one page of two is damaged: the other is saved alone
        return _lone_page(pages, loaded, readable[0], settings.expect_front_first)
    if len(readable) == 1:  # a sheet of one page: a front
        return _Plan(loaded[0], None, pages[0], reason)
    front_at = _front_at([page for page in loaded if page is not None], settings.expect_front_first)
    # AUTO keeps the back too: with no photo box there is nothing to judge handwriting on, and a
    # back that is dropped here could not be asked for again. (A back scanned at another
    # resolution is stored with the front's; the sheet is a failure anyway.)
    keep_back = settings.back_policy is not BackPolicy.NEVER
    back = loaded[1 - front_at] if keep_back else None
    return _Plan(loaded[front_at], back, pages[front_at], reason)


def _lone_page(
    pages: tuple[Path, ...], loaded: list[Page | None], at: int, front_first: bool | None
) -> _Plan:
    """The plan for a sheet of which only page ``at`` can be read.

    The feed order (the declared one, else the default) says whether that page is the front or
    the back; the reason names the side that is missing, so the two cannot disagree.
    """
    first = DEFAULT_FRONT_FIRST if front_first is None else front_first
    is_front = (at == 0) == first
    missing = f"the {'back' if is_front else 'front'} page ({pages[1 - at].name})"
    reason = f"{missing} could not be read; only the other is saved"
    page = loaded[at]
    return (
        _Plan(page, None, pages[at], reason) if is_front else _Plan(None, page, pages[at], reason)
    )


def _load_pages(pages: tuple[Path, ...]) -> list[Page | None]:
    """Each page loaded, or None for one that cannot be read (that costs only that page)."""
    loaded: list[Page | None] = []
    for page in pages:
        try:
            loaded.append(load_frame(page))
        except Exception as error:  # a damaged page must not cost the readable one
            logger.debug("cannot read %s: %s", page.name, str(error) or type(error).__name__)
            loaded.append(None)
    return loaded


def _front_at(loaded: list[Page], expect_front_first: bool | None) -> int:
    """The front page (0 or 1): the normal paper-score decision when both pages show a photo
    box, else the feed order the user declared (page 1 first when nothing is known)."""
    scores = _paper_scores(loaded)
    if scores is not None:
        return decide_sides(scores, expect_front_first, ()).front_at
    front_first = DEFAULT_FRONT_FIRST if expect_front_first is None else expect_front_first
    return 0 if front_first else 1


def _paper_scores(loaded: list[Page]) -> tuple[float, float] | None:
    """The paper score of each page's photo box, or None when either page has no findable box."""
    scores: list[float] = []
    for frame, dpi in loaded:
        try:
            box = detect_photo(frame, dpi).box
        except ValueError:  # NoPhotoFoundError, or a frame the detector refuses
            return None
        scores.append(paper_score(frame[box.y : box.y + box.h, box.x : box.x + box.w]))
    return scores[0], scores[1]
