"""Find and cut out the photo rectangle in a raw scanimage ADF frame.

Layout of a FF-680W frame (RGB, 600 dpi, ``--adf-skew=yes``): a light blue-grey scanner
background surrounds the photo, a thin near-white strip runs along one side edge, and below the
paper there is a grey band followed by a pure-white "tail" the scanner pads to the frame end.
Photo backs are white paper, so the tail is told apart from paper by being a *full-width* run of
white rows at the very end of the frame.

The returned box is the axis-aligned box circumscribing the photo; straightening a skewed print
is the scanner's job (``--adf-skew``), not this module's.
"""

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.pipeline.geometry import mm_to_px, px_to_mm
from fastfoto_linux.pipeline.print_sizes import is_common_print_size

logger = logging.getLogger(__name__)

WORK_DPI = 75  # the box search runs on a copy downsampled to about this resolution
TAIL_WHITE_LEVEL = 250  # grey level (0-255) counted as scanner-white
TAIL_ROW_FRACTION = 0.98  # share of a row that must be white for it to count as a white row
TAIL_DEFECT_MM = 4.0  # non-white runs up to this tall inside the tail are defects, not content
BACKGROUND_PRIOR_RGB = (202.0, 210.0, 219.0)  # measured scanner background (blue-grey, B > R)
# A pixel is a background sample if it is this close (RGB distance) to the prior...
BACKGROUND_PRIOR_TOLERANCE = 20.0
BACKGROUND_NON_WHITE_MARGIN = 10  # ...and this far below TAIL_WHITE_LEVEL in grey
BACKGROUND_MIN_SAMPLES = 200  # with fewer samples than this the prior itself is the background
BG_SAMPLE_NEAR_MM = 3.0  # samples come from between these distances from each side edge
BG_SAMPLE_FAR_MM = 8.0
FOREGROUND_DISTANCE = 40.0  # RGB distance from the background that counts as photo
# Retry threshold for cream or aged backs. It also picks up the soft shadow some prints cast,
# so it is only used when the strict pass finds no photo.
PALE_FOREGROUND_DISTANCE = 20.0
OPEN_KERNEL_MM = 3.0  # opening removes the thin white edge strip, hairs and speckle noise
MIN_PHOTO_MM = 25.0  # smaller boxes are noise, not photos
RGB_CHANNELS = 3


class NoPhotoFoundError(ValueError):
    """The frame contains no photo-sized region that differs from the scanner background."""


@dataclass(frozen=True)
class Box:
    """Axis-aligned rectangle in pixels: top-left corner ``(x, y)`` and size ``(w, h)``."""

    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        if self.w <= 0 or self.h <= 0:
            raise ValueError(f"box must have a positive size, got {self.w}x{self.h}")

    def mm(self, dpi: float) -> tuple[float, float, float, float]:
        """Return ``(x, y, w, h)`` in millimetres at the given resolution."""
        return (
            px_to_mm(self.x, dpi),
            px_to_mm(self.y, dpi),
            px_to_mm(self.w, dpi),
            px_to_mm(self.h, dpi),
        )


@dataclass(frozen=True)
class Detection:
    """A detected photo box plus whether its size is believable for a photo print.

    ``plausible`` is False when the size matches no common print format. That usually means part
    of the photo is close to the scanner background colour (sky, a pale border) and was cut off,
    so callers should cross-check the box against another source such as the matching back side.
    """

    box: Box
    plausible: bool


def _validate_frame(frame: np.ndarray) -> None:
    if frame.dtype != np.uint8 or frame.ndim != RGB_CHANNELS or frame.shape[2] != RGB_CHANNELS:
        raise ValueError(
            f"frame must be an HxWx3 uint8 RGB array, got {frame.dtype} with shape {frame.shape}"
        )
    if frame.size == 0:
        raise ValueError(f"frame is empty: shape {frame.shape}")


def _downsample(frame: np.ndarray, dpi: float) -> tuple[np.ndarray, int]:
    factor = max(1, round(dpi / WORK_DPI))
    height, width = frame.shape[:2]
    small = cv2.resize(
        np.ascontiguousarray(frame),
        (max(1, width // factor), max(1, height // factor)),
        interpolation=cv2.INTER_AREA,
    )
    return small, factor


def _tail_from(white_rows: np.ndarray, work_dpi: float) -> int:
    """First row of the trailing run of white rows, ignoring short non-white defect runs in it."""
    max_defect = mm_to_px(TAIL_DEFECT_MM, work_dpi)
    white = np.flatnonzero(white_rows)
    if white.size == 0 or white_rows.size - 1 - white[-1] > max_defect:
        return white_rows.size
    long_gaps = np.flatnonzero(np.diff(white) - 1 > max_defect)
    return int(white[long_gaps[-1] + 1]) if long_gaps.size else int(white[0])


def _background_colour(small: np.ndarray, grey: np.ndarray, work_dpi: float) -> np.ndarray:
    """Median colour of side-band pixels that look like scanner background, else the prior."""
    near = mm_to_px(BG_SAMPLE_NEAR_MM, work_dpi)
    far = max(near + 1, mm_to_px(BG_SAMPLE_FAR_MM, work_dpi))
    width = small.shape[1]
    if width <= 2 * far:
        raise ValueError(f"frame is too narrow to sample the background: {width} px")
    columns = np.r_[near:far, width - far : width - near]
    pixels = small[:, columns].reshape(-1, RGB_CHANNELS)
    prior = np.asarray(BACKGROUND_PRIOR_RGB, dtype=np.float32)
    close = np.linalg.norm(pixels.astype(np.float32) - prior, axis=1) <= BACKGROUND_PRIOR_TOLERANCE
    dark_enough = grey[:, columns].ravel() < TAIL_WHITE_LEVEL - BACKGROUND_NON_WHITE_MARGIN
    samples = pixels[close & dark_enough]
    if samples.shape[0] < BACKGROUND_MIN_SAMPLES:
        logger.debug("only %d background samples; using the prior colour", samples.shape[0])
        return prior
    background = np.median(samples, axis=0).astype(np.float32)
    logger.debug("background %s from %d samples", background.round(1).tolist(), samples.shape[0])
    return background


def _foreground_mask(
    distance: np.ndarray, threshold: float, tail_rows: np.ndarray, work_dpi: float
) -> np.ndarray:
    """Pixels farther than ``threshold`` from the background, minus the tail, strips and speckle."""
    mask = (distance > threshold).astype(np.uint8)
    mask[tail_rows] = 0
    side = max(1, mm_to_px(OPEN_KERNEL_MM, work_dpi))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (side, side))
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)


def _largest_component(mask: np.ndarray, work_dpi: float) -> tuple[int, int, int, int, int]:
    """Bounding box of the biggest blob, plus how many photo-sized blobs lie outside that box.

    Blobs inside the biggest blob's box are fragments of the same photo (pale areas split it).
    """
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        raise NoPhotoFoundError("no region differs from the scanner background")
    blobs = stats[1:]
    best = int(np.argmax(blobs[:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(v) for v in blobs[best, :4])
    minimum = mm_to_px(MIN_PHOTO_MM, work_dpi)
    left, top = blobs[:, cv2.CC_STAT_LEFT], blobs[:, cv2.CC_STAT_TOP]
    right, bottom = left + blobs[:, cv2.CC_STAT_WIDTH], top + blobs[:, cv2.CC_STAT_HEIGHT]
    separate = (right <= x) | (left >= x + w) | (bottom <= y) | (top >= y + h)
    big = (blobs[:, cv2.CC_STAT_WIDTH] >= minimum) & (blobs[:, cv2.CC_STAT_HEIGHT] >= minimum)
    return x, y, w, h, int((big & separate).sum())


def detect_photo(frame: np.ndarray, dpi: float) -> Detection:
    """Locate the photo in a raw RGB frame: its bounding box in frame pixels plus a size check.

    Raises ``NoPhotoFoundError`` when nothing photo-sized stands out from the background and
    ``ValueError`` for malformed input. ``frame`` is never modified. Logs a warning when the box
    touches the left, right or bottom frame edge (the top edge is normal for ADF scans), when
    a second photo-sized region was ignored, or when the size is implausible for a print.
    """
    _validate_frame(frame)
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")
    small, factor = _downsample(frame, dpi)
    work_dpi = dpi / factor
    grey = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    white_rows = (grey >= TAIL_WHITE_LEVEL).mean(axis=1) >= TAIL_ROW_FRACTION
    tail_rows = white_rows & (np.arange(white_rows.size) >= _tail_from(white_rows, work_dpi))
    background = _background_colour(small, grey, work_dpi)
    distance = np.linalg.norm(small.astype(np.float32) - background, axis=2)
    for threshold in (FOREGROUND_DISTANCE, PALE_FOREGROUND_DISTANCE):
        mask = _foreground_mask(distance, threshold, tail_rows, work_dpi)
        try:
            work_box = _largest_component(mask, work_dpi)
            box = _to_frame_box(work_box[:4], small.shape, frame.shape, factor)
            _require_photo_sized(box, dpi)
        except NoPhotoFoundError as error:
            logger.debug("no photo at distance threshold %g: %s", threshold, error)
            failure = error
        else:
            _report_edges(work_box[:4], small.shape)
            if work_box[4]:
                logger.warning(
                    "ignored %d other photo-sized region(s); only the largest is returned",
                    work_box[4],
                )
            return Detection(box, _check_print_size(box, dpi))
    raise failure


def find_photo_box(frame: np.ndarray, dpi: float) -> Box:
    """Like :func:`detect_photo` but returns only the box."""
    return detect_photo(frame, dpi).box


def _to_frame_box(
    work_box: tuple[int, int, int, int],
    small_shape: tuple[int, ...],
    frame_shape: tuple[int, ...],
    factor: int,
) -> Box:
    """Scale a work-grid box to frame pixels; a box reaching the work edge extends to the frame."""
    sx, sy, sw, sh = work_box
    small_h, small_w = small_shape[:2]
    frame_h, frame_w = frame_shape[:2]
    x1 = frame_w if sx + sw >= small_w else (sx + sw) * factor
    y1 = frame_h if sy + sh >= small_h else (sy + sh) * factor
    return Box(sx * factor, sy * factor, x1 - sx * factor, y1 - sy * factor)


def _require_photo_sized(box: Box, dpi: float) -> None:
    minimum = mm_to_px(MIN_PHOTO_MM, dpi)
    if box.w < minimum or box.h < minimum:
        w_mm, h_mm = box.mm(dpi)[2:]
        raise NoPhotoFoundError(
            f"largest region is {w_mm:.1f}x{h_mm:.1f} mm, below the {MIN_PHOTO_MM:g} mm minimum"
        )


def _report_edges(work_box: tuple[int, int, int, int], small_shape: tuple[int, ...]) -> None:
    sx, sy, sw, sh = work_box
    if sy == 0:
        logger.debug("photo box starts at the top frame edge (normal for ADF scans)")
    touching = {
        "left": sx == 0,
        "right": sx + sw >= small_shape[1],
        "bottom": sy + sh >= small_shape[0],
    }
    for side, touches in touching.items():
        if touches:
            logger.warning("photo box touches the %s frame edge; the photo may be cut off", side)


def _check_print_size(box: Box, dpi: float) -> bool:
    w_mm, h_mm = box.mm(dpi)[2:]
    if is_common_print_size(w_mm, h_mm):
        return True
    logger.warning(
        "box %.0fx%.0f mm matches no common print size; part of the photo may be close to the "
        "scanner background colour (sky, pale border) and was cropped away",
        w_mm,
        h_mm,
    )
    return False


def crop(frame: np.ndarray, box: Box) -> np.ndarray:
    """Return a copy of ``frame`` restricted to ``box``."""
    _validate_frame(frame)
    height, width = frame.shape[:2]
    if box.x < 0 or box.y < 0 or box.x + box.w > width or box.y + box.h > height:
        raise ValueError(f"box {box} lies outside the {width}x{height} frame")
    return frame[box.y : box.y + box.h, box.x : box.x + box.w].copy()
