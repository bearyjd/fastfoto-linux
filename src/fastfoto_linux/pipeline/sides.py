"""Turn the raw pages of one scanimage batch into photos: fronts, backs and back writing."""

import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np

from fastfoto_linux.enhance.faces import ensure_rgb_uint8
from fastfoto_linux.pipeline.crop import Box, Detection, NoPhotoFoundError, crop, detect_photo
from fastfoto_linux.pipeline.geometry import mm_to_px
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

HANDWRITING_MIN_CANDIDATES = 15  # ink blobs needed on a back before it counts as handwritten
HANDWRITING_WORK_DPI = 300  # backs sharper than this are downsampled before blob counting
INK_INSET_MM = 4.0  # ignored band along every edge of a cropped back (the paper edge)
INK_GREY_BELOW = 170  # darker than this is ink; the lab's dot-matrix imprint is fainter
STROKE_HEIGHT_MM = (1.5, 25.0)  # a blob this tall is a letter or a stroke
BLOB_MAX_EXTENT_MM = 50.0  # a blob longer than this is a ruled line or an edge, not writing
PAPER_MIN_GREY = 230  # grey level (0-255) of a paper-white pixel
PAPER_MAX_CHROMA = 40  # max-min over R, G, B of a paper-white pixel (low saturation)
PAPER_SCORE_STRIDE = 4  # paper_score looks at every n-th pixel in each direction
PAPER_TIE_MARGIN = 0.2  # paper scores closer than this cannot tell the two sides apart
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


@dataclass(frozen=True, eq=False)
class Photo:
    """One photo: cropped front, optional cropped back and where they came from.

    ``index`` counts photos from 0 in batch order. ``source_pages`` lists the page paths as
    ``(front_page, back_page)``, or ``(front_page,)`` for a simplex batch; the back page is listed
    even when the back was dropped by the policy. ``back_has_writing`` reports the detection
    whether or not the back was kept. Arrays are never shared with the loaded pages.
    """

    index: int
    front: np.ndarray
    back: np.ndarray | None
    back_has_writing: bool
    source_pages: tuple[Path, ...]
    dpi: int
    side_uncertain: bool = False


def paper_score(img: np.ndarray) -> float:
    """Fraction of pixels that are paper-white: grey >= 230 and low saturation (0.0 to 1.0).

    Photo backs are white paper and fronts are not, so the side with the higher score is the back.
    Only every ``PAPER_SCORE_STRIDE``-th pixel in each direction is looked at.
    """
    ensure_rgb_uint8(img)
    sample = np.ascontiguousarray(img[::PAPER_SCORE_STRIDE, ::PAPER_SCORE_STRIDE])
    grey = cv2.cvtColor(sample, cv2.COLOR_RGB2GRAY)
    chroma = sample.max(axis=2) - sample.min(axis=2)  # uint8 and max >= min, so no overflow
    return float(np.mean((grey >= PAPER_MIN_GREY) & (chroma <= PAPER_MAX_CHROMA)))


def _work_grey(img: np.ndarray, dpi: float) -> tuple[np.ndarray, float]:
    """Grey copy of ``img``, area-downsampled to ``HANDWRITING_WORK_DPI`` if it is sharper."""
    grey = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    if dpi <= HANDWRITING_WORK_DPI:
        return grey, dpi
    scale = HANDWRITING_WORK_DPI / dpi
    size = (max(1, round(grey.shape[1] * scale)), max(1, round(grey.shape[0] * scale)))
    return cv2.resize(grey, size, interpolation=cv2.INTER_AREA), HANDWRITING_WORK_DPI


def handwriting_candidates(back_img: np.ndarray, dpi: int) -> int:
    """Count ink blobs the size of letters or strokes on a cropped RGB back.

    Ink is anything darker than ``INK_GREY_BELOW`` more than ``INK_INSET_MM`` from every edge, so
    the paper edge and the faint lab imprint do not count. A blob is a candidate when it is
    ``STROKE_HEIGHT_MM`` tall and no longer than ``BLOB_MAX_EXTENT_MM`` (ruled lines and borders
    are longer). Raises ``ValueError`` for a malformed image or a non-positive ``dpi``.
    """
    ensure_rgb_uint8(back_img)
    grey, work_dpi = _work_grey(back_img, dpi)
    inset = mm_to_px(INK_INSET_MM, work_dpi)  # also validates dpi
    height, width = grey.shape
    if height <= 2 * inset or width <= 2 * inset:
        logger.debug("back is too small to look for writing: %dx%d px", width, height)
        return 0
    ink = (grey[inset : height - inset, inset : width - inset] < INK_GREY_BELOW).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    blob_h, blob_w = stats[1:, cv2.CC_STAT_HEIGHT], stats[1:, cv2.CC_STAT_WIDTH]
    low, high = (mm_to_px(mm, work_dpi) for mm in STROKE_HEIGHT_MM)
    too_long = np.maximum(blob_h, blob_w) > mm_to_px(BLOB_MAX_EXTENT_MM, work_dpi)
    return int(((blob_h >= low) & (blob_h <= high) & ~too_long).sum())


@dataclass(frozen=True)
class HandwritingEvidence:
    """Both back-writing measures: blob candidates (the gate) and pen strokes (not a gate yet)."""

    candidates: int
    pen_strokes: int


def handwriting_evidence(back_img: np.ndarray, dpi: int) -> HandwritingEvidence:
    """Candidate-blob and pen-stroke counts of a cropped RGB back."""
    raise NotImplementedError


def has_handwriting(back_img: np.ndarray, dpi: int) -> bool:
    """True if a cropped back carries at least ``HANDWRITING_MIN_CANDIDATES`` ink blobs."""
    return handwriting_candidates(back_img, dpi) >= HANDWRITING_MIN_CANDIDATES


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


def _load_page(path: Path, loader: FrameLoader) -> _Page:
    frame, dpi = loader(path)
    try:
        detection = detect_photo(frame, dpi)
    except NoPhotoFoundError as error:
        logger.debug("%s: no photo found: %s", path.name, error)
        detection = None
    return _Page(path, frame, dpi, detection)


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


def _front_index(number: int, scores: tuple[float, float], expect_front_first: bool | None) -> int:
    """Which page of the sheet (0 or 1) is the front: the one with the lower paper score."""
    first, second = scores
    if abs(first - second) >= PAPER_TIE_MARGIN:
        return 0 if first < second else 1
    if expect_front_first is None:
        raise BatchError(
            f"sheet {number}: both pages look alike (paper scores {first:.2f} and {second:.2f}); "
            "set expect_front_first to say which page of a sheet is scanned first"
        )
    logger.info(
        "sheet %d: paper scores %.2f and %.2f cannot tell front from back; "
        "falling back to page parity (front %s)",
        number,
        first,
        second,
        "first" if expect_front_first else "second",
    )
    return 0 if expect_front_first else 1


def _sheet_photo(
    index: int,
    pages: tuple[_Page, _Page],
    back_policy: BackPolicy,
    expect_front_first: bool | None,
) -> Photo:
    first, second = pages
    if first.dpi != second.dpi:
        raise BatchError(f"sheet {index + 1}: pages differ in dpi ({first.dpi} and {second.dpi})")
    boxes = _own_boxes(index + 1, first, second)
    scores = (paper_score(_view(first, boxes[0])), paper_score(_view(second, boxes[1])))
    front_at = _front_index(index + 1, scores, expect_front_first)
    front_page, back_page = pages[front_at], pages[1 - front_at]
    front_box, back_box = boxes[front_at], boxes[1 - front_at]
    back_detection = back_page.detection
    if back_detection is not None and front_needs_correction(
        front_page.detection, back_detection.box, front_page.dpi
    ):
        front_box = mirrored_front_box(back_detection.box, front_page.frame.shape, front_page.dpi)
        logger.info("sheet %d: front box taken from the back box (mirrored)", index + 1)
    writing = has_handwriting(_view(back_page, back_box), back_page.dpi)
    keep_back = back_policy is BackPolicy.ALWAYS or (back_policy is BackPolicy.AUTO and writing)
    return Photo(
        index=index,
        front=crop(front_page.frame, front_box),
        back=crop(back_page.frame, back_box) if keep_back else None,
        back_has_writing=writing,
        source_pages=(front_page.path, back_page.path),
        dpi=front_page.dpi,
    )


def _front_only_photo(index: int, path: Path, loader: FrameLoader) -> Photo:
    page = _load_page(path, loader)
    if page.detection is None:
        raise BatchError(f"{path.name}: no photo found")
    return Photo(index, crop(page.frame, page.detection.box), None, False, (path,), page.dpi)


def _generate(
    pages: tuple[Path, ...],
    duplex: bool,
    back_policy: BackPolicy,
    expect_front_first: bool | None,
    loader: FrameLoader,
) -> Iterator[Photo]:
    sheet_size = 2 if duplex else 1
    for index in range(len(pages) // sheet_size):
        sheet = pages[index * sheet_size : (index + 1) * sheet_size]
        if not duplex:
            yield _front_only_photo(index, sheet[0], loader)
            continue
        loaded = (_load_page(sheet[0], loader), _load_page(sheet[1], loader))
        yield _sheet_photo(index, loaded, back_policy, expect_front_first)
    if duplex and len(pages) % 2:
        yield _front_only_photo(len(pages) // 2, pages[-1], loader)


def iter_photos(  # noqa: PLR0913
    pages: Sequence[Path],
    *,
    duplex: bool,
    back_policy: BackPolicy = BackPolicy.AUTO,
    expect_front_first: bool | None = None,
    allow_odd: bool = False,
    loader: FrameLoader = load_frame,
) -> Iterator[Photo]:
    """Yield the photos of a batch one sheet at a time, so only one sheet is in memory.

    The page count is checked immediately (``BatchError`` for an odd duplex batch unless
    ``allow_odd``); loading, cropping and pairing happen as the iterator is consumed. See
    :func:`assemble_photos` for the rules.
    """
    paths = tuple(pages)
    if duplex and len(paths) % 2 and not allow_odd:
        raise BatchError(
            f"odd number of pages ({len(paths)}) in a duplex batch; every sheet has two sides "
            "(pass allow_odd=True to treat the last page as a front without a back)"
        )
    return _generate(paths, duplex, back_policy, expect_front_first, loader)


def assemble_photos(  # noqa: PLR0913
    pages: Sequence[Path],
    *,
    duplex: bool,
    back_policy: BackPolicy = BackPolicy.AUTO,
    expect_front_first: bool | None = None,
    allow_odd: bool = False,
    loader: FrameLoader = load_frame,
) -> tuple[Photo, ...]:
    """Load, crop and pair the pages of a batch into photos.

    Duplex: pages ``(1, 2), (3, 4), ...`` are the two sides of one sheet each. Which side is the
    front is decided by content (the side with the lower :func:`paper_score` is the front), not
    parity; when the scores differ by less than ``PAPER_TIE_MARGIN`` the choice falls back to
    ``expect_front_first`` (True: the first page of a sheet is the front) and is logged, and with
    no expectation it is a ``BatchError``. A front whose own crop is missing or doubtful takes
    its box from the mirrored back box (:func:`front_needs_correction`). The back is kept
    according to ``back_policy``; ``back_has_writing`` is always reported. An odd page count is a
    ``BatchError`` unless ``allow_odd``, which makes the last page a front without a back.
    Simplex (``duplex=False``): every page is a front. A page with no photo is a ``BatchError``.
    """
    return tuple(
        iter_photos(
            pages,
            duplex=duplex,
            back_policy=back_policy,
            expect_front_first=expect_front_first,
            allow_odd=allow_odd,
            loader=loader,
        )
    )
