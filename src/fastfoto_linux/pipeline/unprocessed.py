"""Save the whole pages of a sheet that could not be turned into a photo.

The sheet keeps its own number in the sequence, so that no photo of the batch goes missing
unnoticed: its front page is written as ``<prefix>_NNNN_unprocessed.jpg`` and its back as
``<prefix>_NNNN_unprocessed_b.jpg``. Nothing is cut away except the scanner's white tail.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from fastfoto_linux.output import WrittenFiles, write_unprocessed
from fastfoto_linux.pipeline.crop import detect_photo, trim_tail
from fastfoto_linux.pipeline.ink import paper_score
from fastfoto_linux.pipeline.io import load_frame, scan_time
from fastfoto_linux.pipeline.side_order import DEFAULT_FRONT_FIRST, decide_sides
from fastfoto_linux.pipeline.sides import BackPolicy, BatchError, NoPhotoOnSheetError

if TYPE_CHECKING:  # process.py imports this module
    from fastfoto_linux.pipeline.process import ProcessSettings

logger = logging.getLogger(__name__)

NO_PHOTO_REASON = "the photo's edges were not found (two items fed together?)"

Page = tuple[np.ndarray, int]
"""A loaded page: ``(frame, dpi)``."""


def plain_reason(error: BatchError) -> str:
    """Why the sheet is not a photo, in words for the user (the error's own text is for logs)."""
    if isinstance(error, NoPhotoOnSheetError):
        return NO_PHOTO_REASON
    return str(error).removeprefix(f"sheet {error.sheet}: ")


def save_unprocessed(
    pages: tuple[Path, ...], settings: "ProcessSettings", reason: str
) -> WrittenFiles | None:
    """Write the one or two ``pages`` of a sheet (in feed order) whole; None if that fails.

    The front is chosen like a normal sheet's when both pages show a photo box, else by the feed
    order ``settings`` declares. The back follows the back policy. Never raises an ``Exception``:
    a page that cannot be read or files that cannot be written leave the sheet as a plain
    failure, which is the caller's business.
    """
    try:
        return _save(pages, settings, reason)
    except Exception as error:  # the fallback is the plain failure the caller already has
        names = ", ".join(page.name for page in pages)
        logger.error("cannot save %s whole: %s", names, str(error) or type(error).__name__)
        logger.debug("details of the failure to save %s whole", names, exc_info=True)
        return None


def _save(pages: tuple[Path, ...], settings: "ProcessSettings", reason: str) -> WrittenFiles:
    loaded = [load_frame(page) for page in pages]
    two_sided = len(loaded) == 2  # noqa: PLR2004 - a duplex sheet; a lone page is a front
    front_at = _front_at(loaded, settings.expect_front_first) if two_sided else 0
    frame, dpi = loaded[front_at]
    back = None
    if two_sided and settings.back_policy is not BackPolicy.NEVER:
        # AUTO keeps the back too: with no photo box there is nothing to judge handwriting on,
        # and a back that is dropped here could not be asked for again. (A back scanned at
        # another resolution is stored with the front's; the sheet is a failure anyway.)
        back_frame, back_dpi = loaded[1 - front_at]
        back = trim_tail(back_frame, back_dpi)
    files = write_unprocessed(
        trim_tail(frame, dpi),
        dpi=dpi,
        output_root=settings.output_root,
        reason=reason,
        back=back,
        album=settings.album,
        prefix=settings.prefix,
        date=settings.date,
        notes=settings.notes,
        scanned_at=scan_time(pages[front_at]),
        quality=settings.quality,
    )
    logger.info("saved %s whole: %s", ", ".join(page.name for page in pages), reason)
    return files


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
