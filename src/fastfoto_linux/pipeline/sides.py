"""Turn the raw pages of one scanimage batch into photos: fronts, backs and back writing."""

import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np

from fastfoto_linux.pipeline.crop import Box, Detection, NoPhotoFoundError, crop, detect_photo
from fastfoto_linux.pipeline.geometry import mm_to_px
from fastfoto_linux.pipeline.ink import (
    HANDWRITING_MIN_CANDIDATES,
    HandwritingEvidence,
    handwriting_candidates,
    handwriting_evidence,
    has_handwriting,
    paper_score,
)
from fastfoto_linux.pipeline.io import load_frame

__all__ = [
    "BackPolicy",
    "BatchError",
    "HandwritingEvidence",
    "Photo",
    "assemble_photos",
    "front_needs_correction",
    "handwriting_candidates",
    "handwriting_evidence",
    "has_handwriting",
    "iter_photos",
    "mirrored_front_box",
    "paper_score",
]

logger = logging.getLogger(__name__)

PAPER_TIE_MARGIN = 0.2  # paper scores closer than this cannot tell the two sides apart
BACK_LIKE_PAPER_SCORE = 0.75  # a lone page this paper-white is a back (real fronts stay below)
DEFAULT_FRONT_FIRST = True  # tie with no expectation and no resolved sheet: page 1 is the front
TIE_BREAK_RECENT_SHEETS = 8  # a tie follows the page order of this many latest confident sheets
FRONT_FROM_BACK_X_OFFSET_MM = 1.2  # measured shift of the front box against the mirrored back box
FRONT_BACK_SIZE_TOLERANCE_MM = 3.0  # a front box this much off the back's size is distrusted

FrameLoader = Callable[[Path], tuple[np.ndarray, int]]


class BatchError(ValueError):
    """The pages of a batch cannot be turned into photos (odd page count, no photo, ...)."""


class BackPolicy(StrEnum):
    """Which photo backs to keep: only handwritten ones (AUTO, like FastFoto), all, or none."""

    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


@dataclass(frozen=True)
class _Settings:
    """The caller's choices that every sheet of a batch shares."""

    back_policy: BackPolicy
    expect_front_first: bool | None
    loader: FrameLoader


@dataclass(frozen=True, eq=False)
class Photo:
    """One photo: cropped front, optional cropped back and where they came from.

    ``index`` counts photos from 0 in batch order. ``source_pages`` lists the page paths as
    ``(front_page, back_page)``, or ``(front_page,)`` for a simplex batch; the back page is listed
    even when the back was dropped by the policy. ``back_has_writing`` reports the detection
    whether or not the back was kept. Arrays are never shared with the loaded pages.
    ``side_uncertain`` is True when the sides of the sheet could not be told apart by content (the
    decision came from page parity) or a lone last page looks like a back; such a photo always
    keeps its back, whatever the policy, because it may in fact be the front.
    """

    index: int
    front: np.ndarray
    back: np.ndarray | None
    back_has_writing: bool
    source_pages: tuple[Path, ...]
    dpi: int
    side_uncertain: bool = False


def _clamped(box: Box, frame_shape: tuple[int, ...]) -> Box:
    """The part of ``box`` inside the frame (``Box`` raises if nothing is left)."""
    frame_h, frame_w = frame_shape[:2]
    x0, y0 = max(0, box.x), max(0, box.y)
    x1, y1 = min(frame_w, box.x + box.w), min(frame_h, box.y + box.h)
    return Box(x0, y0, x1 - x0, y1 - y0)


def mirrored_front_box(back_box: Box, frame_shape: tuple[int, ...], dpi: float) -> Box:
    """The other side's photo box, from this side's: mirrored in x, shifted, clamped to the frame.

    A sheet is scanned with the photo's far edge leading, so the front photo sits where the back
    photo does, mirrored across the frame, plus ``FRONT_FROM_BACK_X_OFFSET_MM`` (measured on real
    FF-680W sheets). ``frame_shape`` is the frame the box is wanted in. The mapping is its own
    inverse, so it also gives a back box from a front box.
    """
    frame_w = frame_shape[1]
    x = frame_w - (back_box.x + back_box.w) + mm_to_px(FRONT_FROM_BACK_X_OFFSET_MM, dpi)
    return _clamped(Box(x, back_box.y, back_box.w, back_box.h), frame_shape)


def front_needs_correction(front: Detection | None, back_box: Box, dpi: float) -> bool:
    """True if the front detection is missing, implausible or sized unlike the back's box.

    Backs are white paper and crop reliably; fronts can lose an edge that resembles the scanner
    background. The tolerance is ``FRONT_BACK_SIZE_TOLERANCE_MM`` in width and in height.
    """
    if front is None or not front.plausible:
        return True
    tolerance = mm_to_px(FRONT_BACK_SIZE_TOLERANCE_MM, dpi)
    return abs(front.box.w - back_box.w) > tolerance or abs(front.box.h - back_box.h) > tolerance


@dataclass(frozen=True)
class _Page:
    """A loaded page and its own photo detection (``None`` when nothing was found)."""

    path: Path
    frame: np.ndarray
    dpi: int
    detection: Detection | None


def _detect(path: Path, frame: np.ndarray, dpi: int) -> Detection | None:
    try:
        return detect_photo(frame, dpi)
    except NoPhotoFoundError as error:
        logger.debug("%s: no photo found: %s", path.name, error)
        return None


def _load_page(number: int, path: Path, loader: FrameLoader) -> _Page:
    """Load and detect one page; any failure becomes a ``BatchError`` naming sheet and page."""
    try:
        frame, dpi = loader(path)
        return _Page(path, frame, dpi, _detect(path, frame, dpi))
    except Exception as error:
        raise BatchError(f"sheet {number}: cannot read {path.name}: {error}") from error


def _view(page: _Page, box: Box) -> np.ndarray:
    """The pixels of ``box`` without copying (for scoring and counting only)."""
    return page.frame[box.y : box.y + box.h, box.x : box.x + box.w]


def _own_boxes(number: int, first: _Page, second: _Page) -> tuple[Box, Box]:
    """Each page's detected box; a page with none borrows the other page's, mirrored."""
    one, two = first.detection, second.detection
    if one is None and two is None:
        raise BatchError(f"sheet {number}: no photo found on either page")
    box_one = one.box if one else mirrored_front_box(two.box, first.frame.shape, first.dpi)
    box_two = two.box if two else mirrored_front_box(one.box, second.frame.shape, second.dpi)
    return box_one, box_two


def _majority(front_first_sheets: int, back_first_sheets: int) -> bool | None:
    """The page order most resolved sheets of this batch had, or None when it is an even split."""
    if front_first_sheets == back_first_sheets:
        return None
    return front_first_sheets > back_first_sheets


def _tie_break(expect_front_first: bool | None, majority: bool | None) -> tuple[bool, str]:
    """Front-first or not for a sheet content cannot decide, and where that answer came from."""
    if expect_front_first is not None:
        return expect_front_first, "the expected"
    if majority is not None:
        return majority, "the batch-majority"
    return DEFAULT_FRONT_FIRST, "the default"


def _front_index(
    number: int,
    scores: tuple[float, float],
    expect_front_first: bool | None,
    majority: bool | None,
) -> tuple[int, bool]:
    """Which page of the sheet (0 or 1) is the front, and whether that is only a tie-break.

    The page with the lower paper score is the front. Scores within ``PAPER_TIE_MARGIN`` are a
    tie: ``expect_front_first`` decides, else the order most resolved sheets of the batch had, else
    ``DEFAULT_FRONT_FIRST``. Nothing here raises: a wrong guess is flagged, never a lost photo.
    """
    first, second = scores
    if abs(first - second) >= PAPER_TIE_MARGIN:
        front_at = 0 if first < second else 1
        if expect_front_first is not None and (front_at == 0) != expect_front_first:
            logger.info(
                "sheet %d: the content says page %d is the front, which contradicts "
                "expect_front_first=%s; using the content",
                number,
                front_at + 1,
                expect_front_first,
            )
        return front_at, False
    front_first, source = _tie_break(expect_front_first, majority)
    logger.info(
        "sheet %d: paper scores %.2f and %.2f cannot tell front from back; using %s page parity "
        "(front scanned %s)",
        number,
        first,
        second,
        source,
        "first" if front_first else "second",
    )
    return (0 if front_first else 1), True


def _front_box(number: int, front: _Page, back: _Page, own_box: Box) -> Box:
    """The front's crop box: its own, or the back's mirrored when the back is the better witness.

    A back box only corrects a front when it is plausible itself; against an implausible one the
    front keeps its box and the disagreement is logged.
    """
    back_detection = back.detection
    if back_detection is None or not front_needs_correction(
        front.detection, back_detection.box, front.dpi
    ):
        return own_box
    if front.detection is not None and not back_detection.plausible:
        logger.warning(
            "sheet %d: front and back boxes disagree, but the back box matches no common print "
            "size either; keeping the front box",
            number,
        )
        return own_box
    reason = "no front photo found" if front.detection is None else "front box disagrees with back"
    logger.info("sheet %d: %s; front box taken from the back box (mirrored)", number, reason)
    return mirrored_front_box(back_detection.box, front.frame.shape, front.dpi)


def _sheet_photo(
    index: int, pages: tuple[_Page, _Page], settings: _Settings, majority: bool | None
) -> Photo:
    number = index + 1
    first, second = pages
    if first.dpi != second.dpi:
        raise BatchError(f"sheet {number}: pages differ in dpi ({first.dpi} and {second.dpi})")
    boxes = _own_boxes(number, first, second)
    scores = (paper_score(_view(first, boxes[0])), paper_score(_view(second, boxes[1])))
    front_at, uncertain = _front_index(number, scores, settings.expect_front_first, majority)
    front_page, back_page = pages[front_at], pages[1 - front_at]
    front_box = _front_box(number, front_page, back_page, boxes[front_at])
    evidence = handwriting_evidence(_view(back_page, boxes[1 - front_at]), back_page.dpi)
    logger.info(
        "sheet %d: back writing evidence: %d candidate blobs (gate %d), %d pen strokes "
        "(reported only)",
        number,
        evidence.candidates,
        HANDWRITING_MIN_CANDIDATES,
        evidence.pen_strokes,
    )
    policy = settings.back_policy
    keep_back = (
        uncertain
        or policy is BackPolicy.ALWAYS
        or (policy is BackPolicy.AUTO and evidence.handwritten)
    )
    return Photo(
        index=index,
        front=crop(front_page.frame, front_box),
        back=crop(back_page.frame, boxes[1 - front_at]) if keep_back else None,
        back_has_writing=evidence.handwritten,
        source_pages=(front_page.path, back_page.path),
        dpi=front_page.dpi,
        side_uncertain=uncertain,
    )


def _front_only_photo(index: int, path: Path, loader: FrameLoader, *, dangling: bool) -> Photo:
    """A photo from a page taken as a front: a simplex page or the odd last page of a duplex batch.

    A dangling page that is paper-white looks like a back whose front is missing: it is kept as
    the front, as asked, but flagged ``side_uncertain`` with a warning.
    """
    page = _load_page(index + 1, path, loader)
    if page.detection is None:
        raise BatchError(f"sheet {index + 1}: {path.name}: no photo found")
    suspicious = dangling and paper_score(_view(page, page.detection.box)) >= BACK_LIKE_PAPER_SCORE
    if suspicious:
        logger.warning(
            "sheet %d: the last page (%s) looks like a back, not a front; its front is missing",
            index + 1,
            path.name,
        )
    crop_ = crop(page.frame, page.detection.box)
    return Photo(index, crop_, None, False, (path,), page.dpi, side_uncertain=suspicious)


def _duplex_photo(
    index: int, paths: tuple[Path, Path], settings: _Settings, majority: bool | None
) -> Photo:
    """Load both pages of a sheet and build its photo; the full frames die when this returns."""
    loader = settings.loader
    pages = (_load_page(index + 1, paths[0], loader), _load_page(index + 1, paths[1], loader))
    return _sheet_photo(index, pages, settings, majority)


def _generate(pages: tuple[Path, ...], duplex: bool, settings: _Settings) -> Iterator[Photo]:
    if not duplex:
        for index, path in enumerate(pages):
            yield _front_only_photo(index, path, settings.loader, dangling=False)
        return
    front_first_sheets = back_first_sheets = 0
    for index in range(len(pages) // 2):
        paths = (pages[2 * index], pages[2 * index + 1])
        majority = _majority(front_first_sheets, back_first_sheets)
        photo = _duplex_photo(index, paths, settings, majority)
        if not photo.side_uncertain:
            front_first = photo.source_pages[0] == paths[0]
            front_first_sheets += front_first
            back_first_sheets += not front_first
        yield photo
    if len(pages) % 2:
        yield _front_only_photo(len(pages) // 2, pages[-1], settings.loader, dangling=True)


def iter_photos(  # noqa: PLR0913
    pages: Sequence[Path],
    *,
    duplex: bool,
    back_policy: BackPolicy = BackPolicy.AUTO,
    expect_front_first: bool | None = None,
    allow_odd: bool = False,
    loader: FrameLoader = load_frame,
    on_sheet_error: Callable[[BatchError], None] | None = None,
) -> Iterator[Photo]:
    """Yield the photos of a batch one sheet at a time, so only one sheet is in memory.

    The page count is checked immediately (``BatchError`` for an odd duplex batch unless
    ``allow_odd``); loading, cropping and pairing happen as the iterator is consumed. See
    :func:`assemble_photos` for the rules.
    """
    if on_sheet_error is not None:
        raise NotImplementedError("on_sheet_error")
    paths = tuple(pages)
    if duplex and len(paths) % 2 and not allow_odd:
        raise BatchError(
            f"odd number of pages ({len(paths)}) in a duplex batch; every sheet has two sides "
            "(pass allow_odd=True to treat the last page as a front without a back)"
        )
    return _generate(paths, duplex, _Settings(back_policy, expect_front_first, loader))


def assemble_photos(  # noqa: PLR0913
    pages: Sequence[Path],
    *,
    duplex: bool,
    back_policy: BackPolicy = BackPolicy.AUTO,
    expect_front_first: bool | None = None,
    allow_odd: bool = False,
    loader: FrameLoader = load_frame,
    on_sheet_error: Callable[[BatchError], None] | None = None,
) -> tuple[Photo, ...]:
    """Load, crop and pair the pages of a batch into photos.

    Duplex: pages ``(1, 2), (3, 4), ...`` are the two sides of one sheet each. Which side is the
    front is decided by content (the side with the lower :func:`paper_score` is the front), not
    parity. When the scores differ by less than ``PAPER_TIE_MARGIN`` the sides cannot be told
    apart and the order comes from, in turn, ``expect_front_first`` (True: the first page of a
    sheet is the front), the order most already-resolved sheets of this batch had, and finally
    "first page is the front". That never raises and never drops anything: such a photo has
    ``side_uncertain`` set and keeps its back whatever the policy. A front whose own crop is
    missing or doubtful takes its box from the mirrored back box (:func:`front_needs_correction`,
    only from a plausible back box). The back is kept according to ``back_policy``;
    ``back_has_writing`` is always reported (gate: ``HANDWRITING_MIN_CANDIDATES`` ink blobs) and
    the pen-stroke count is logged next to it. An odd page count is a ``BatchError`` unless
    ``allow_odd``, which makes the last page a front without a back (flagged uncertain if it looks
    like a back). Simplex (``duplex=False``): every page is a front. A page that cannot be read
    or holds no photo is a ``BatchError`` naming the sheet.
    """
    return tuple(
        iter_photos(
            pages,
            duplex=duplex,
            back_policy=back_policy,
            expect_front_first=expect_front_first,
            allow_odd=allow_odd,
            loader=loader,
            on_sheet_error=on_sheet_error,
        )
    )
