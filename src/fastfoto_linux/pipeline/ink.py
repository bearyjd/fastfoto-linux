"""Paper score and back-writing detection on cropped RGB photo sides."""

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.imaging import ensure_rgb_uint8
from fastfoto_linux.pipeline.geometry import mm_to_px

logger = logging.getLogger(__name__)

# A back counts as handwritten from two ink blobs on. Measured on 18 hand-labelled backs against
# 1306 others: short dated notes score 2-3, so 2 finds all 18, while about 6% of blank backs (lab
# imprints) also reach 2. A kept blank back costs nothing; a dropped note is lost for good.
HANDWRITING_MIN_CANDIDATES = 2
HANDWRITING_WORK_DPI = 300  # backs sharper than this are downsampled before blob counting
INK_INSET_MM = 4.0  # ignored band along every edge of a cropped back (the paper edge)
INK_GREY_BELOW = 170  # darker than this is ink; the lab's dot-matrix imprint is mostly fainter
STROKE_HEIGHT_MM = (1.5, 25.0)  # a blob this tall is a letter or a stroke
# A blob longer than this is a ruled line, a paper-edge shadow or a border, not writing. The cap
# also drops one long run of joined-up cursive, which is accepted: writing nearly always breaks
# into several blobs, and the gate needs only two.
BLOB_MAX_EXTENT_MM = 50.0
# A pen stroke is a thin dark blob: sparse in its bounding box and with a dark core. Reported next
# to the candidate count but not used as a gate yet (leave-one-out recall was only 16 of 18).
PEN_FILL_MAX = 0.30  # blob area / bounding-box area
PEN_CORE_GREY_MAX = 110  # darkest pixel of the blob
# Paper-white, loosely enough to take cream and aged paper (grey ~215-235, chroma up to ~45):
# measured on real fronts the paper share stays at or below 0.51 at the 99th percentile.
PAPER_MIN_GREY = 200  # grey level (0-255) of a paper-white pixel
PAPER_MAX_CHROMA = 45  # max-min over R, G, B of a paper-white pixel (low saturation)
PAPER_SCORE_STRIDE = 4  # paper_score looks at every n-th pixel in each direction


def paper_score(img: np.ndarray) -> float:
    """Fraction of pixels that are paper-white: grey >= 200 and low saturation (0.0 to 1.0).

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


@dataclass(frozen=True)
class _Blobs:
    """Ink blobs of a back: the analysed grey area, its label image and one stats row per blob."""

    grey: np.ndarray
    labels: np.ndarray
    stats: np.ndarray
    dpi: float


def _ink_blobs(back_img: np.ndarray, dpi: float) -> _Blobs | None:
    """Label the ink (darker than ``INK_GREY_BELOW``) inside the inset; None if there is no room.

    Raises ``ValueError`` for a malformed image or a non-positive ``dpi``.
    """
    ensure_rgb_uint8(back_img)
    grey, work_dpi = _work_grey(back_img, dpi)
    inset = mm_to_px(INK_INSET_MM, work_dpi)  # also validates dpi
    height, width = grey.shape
    if height <= 2 * inset or width <= 2 * inset:
        logger.debug("back is too small to look for writing: %dx%d px", width, height)
        return None
    area = grey[inset : height - inset, inset : width - inset]
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        (area < INK_GREY_BELOW).astype(np.uint8), connectivity=8
    )
    return _Blobs(area, labels, stats[1:], work_dpi)


def _stroke_sized(blobs: _Blobs) -> np.ndarray:
    low, high = (mm_to_px(mm, blobs.dpi) for mm in STROKE_HEIGHT_MM)
    height = blobs.stats[:, cv2.CC_STAT_HEIGHT]
    return (height >= low) & (height <= high)


def _candidates(blobs: _Blobs) -> np.ndarray:
    extent = np.maximum(blobs.stats[:, cv2.CC_STAT_HEIGHT], blobs.stats[:, cv2.CC_STAT_WIDTH])
    return _stroke_sized(blobs) & (extent <= mm_to_px(BLOB_MAX_EXTENT_MM, blobs.dpi))


def _darkest_pixel(blobs: _Blobs) -> np.ndarray:
    """The darkest grey level inside each blob."""
    flat = blobs.labels.ravel()
    inked = np.flatnonzero(flat)
    order = inked[np.argsort(flat[inked], kind="stable")]
    starts = np.searchsorted(flat[order], np.arange(1, len(blobs.stats) + 1))
    return np.minimum.reduceat(blobs.grey.ravel()[order], starts)


def _pen_strokes(blobs: _Blobs) -> np.ndarray:
    stats = blobs.stats
    box_area = stats[:, cv2.CC_STAT_HEIGHT] * stats[:, cv2.CC_STAT_WIDTH]
    sparse = stats[:, cv2.CC_STAT_AREA] <= PEN_FILL_MAX * box_area
    return _stroke_sized(blobs) & sparse & (_darkest_pixel(blobs) <= PEN_CORE_GREY_MAX)


def handwriting_candidates(back_img: np.ndarray, dpi: int) -> int:
    """Count ink blobs the size of letters or strokes on a cropped RGB back.

    Ink is anything darker than ``INK_GREY_BELOW`` more than ``INK_INSET_MM`` from every edge, so
    the paper edge and most of the lab imprint do not count. A blob is a candidate when it is
    ``STROKE_HEIGHT_MM`` tall and no longer than ``BLOB_MAX_EXTENT_MM`` (ruled lines, borders and
    edge shadows are longer). Backs sharper than ``HANDWRITING_WORK_DPI`` are area-downsampled
    first. Raises ``ValueError`` for a malformed image or a non-positive ``dpi``.
    """
    blobs = _ink_blobs(back_img, dpi)
    return 0 if blobs is None else int(_candidates(blobs).sum())


@dataclass(frozen=True)
class HandwritingEvidence:
    """Both back-writing measures: blob candidates (the gate) and pen strokes (not a gate yet)."""

    candidates: int
    pen_strokes: int

    @property
    def handwritten(self) -> bool:
        return self.candidates >= HANDWRITING_MIN_CANDIDATES


def handwriting_evidence(back_img: np.ndarray, dpi: int) -> HandwritingEvidence:
    """Candidate-blob and pen-stroke counts of a cropped RGB back.

    ``candidates`` is :func:`handwriting_candidates`. ``pen_strokes`` counts the stroke-sized
    blobs that are also sparse (area at most ``PEN_FILL_MAX`` of the bounding box) and dark
    (core at most ``PEN_CORE_GREY_MAX``): pen, not printed text or a dark imprint. It is reported
    and logged but gates nothing yet; the same ``ValueError`` rules apply.
    """
    blobs = _ink_blobs(back_img, dpi)
    if blobs is None or len(blobs.stats) == 0:
        return HandwritingEvidence(0, 0)
    return HandwritingEvidence(int(_candidates(blobs).sum()), int(_pen_strokes(blobs).sum()))


def has_handwriting(back_img: np.ndarray, dpi: int) -> bool:
    """True if a cropped back carries at least ``HANDWRITING_MIN_CANDIDATES`` ink blobs."""
    return handwriting_candidates(back_img, dpi) >= HANDWRITING_MIN_CANDIDATES
