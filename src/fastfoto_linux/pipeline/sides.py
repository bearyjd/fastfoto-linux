"""Turn the raw pages of one scanimage batch into photos: fronts, backs and back writing."""

import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np

from fastfoto_linux.pipeline.crop import Box, Detection
from fastfoto_linux.pipeline.io import load_frame

__all__ = [
    "BackPolicy",
    "BatchError",
    "Photo",
    "assemble_photos",
    "front_needs_correction",
    "handwriting_candidates",
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


def paper_score(img: np.ndarray) -> float:
    """Fraction of pixels that are paper-white: grey >= 230 and low saturation (0.0 to 1.0)."""
    raise NotImplementedError


def handwriting_candidates(back_img: np.ndarray, dpi: int) -> int:
    """Count ink blobs the size of letters or strokes on a cropped RGB back."""
    raise NotImplementedError


def has_handwriting(back_img: np.ndarray, dpi: int) -> bool:
    """True if a cropped back carries at least ``HANDWRITING_MIN_CANDIDATES`` ink blobs."""
    raise NotImplementedError


def mirrored_front_box(back_box: Box, frame_shape: tuple[int, ...], dpi: float) -> Box:
    """The front's photo box derived from the back's, clamped to the front frame."""
    raise NotImplementedError


def front_needs_correction(front: Detection | None, back_box: Box, dpi: float) -> bool:
    """True if the front detection is missing, implausible or sized unlike the back's box."""
    raise NotImplementedError


def iter_photos(  # noqa: PLR0913
    pages: Sequence[Path],
    *,
    duplex: bool,
    back_policy: BackPolicy = BackPolicy.AUTO,
    expect_front_first: bool | None = None,
    allow_odd: bool = False,
    loader: FrameLoader = load_frame,
) -> Iterator[Photo]:
    """Yield the photos of a batch one sheet at a time (see :func:`assemble_photos`)."""
    raise NotImplementedError


def assemble_photos(  # noqa: PLR0913
    pages: Sequence[Path],
    *,
    duplex: bool,
    back_policy: BackPolicy = BackPolicy.AUTO,
    expect_front_first: bool | None = None,
    allow_odd: bool = False,
    loader: FrameLoader = load_frame,
) -> tuple[Photo, ...]:
    """Load, crop and pair the pages of a batch into photos."""
    raise NotImplementedError
