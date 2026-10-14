"""Find and cut out the photo rectangle in a raw scanimage ADF frame.

Layout of a FF-680W frame (RGB, 600 dpi, ``--adf-skew=yes``): a light blue-grey scanner
background surrounds the photo, a thin near-white strip runs along one side edge, and below the
paper there is a grey band followed by a pure-white "tail" the scanner pads to the frame end.
Photo backs are white paper, so the tail is told apart from paper by being a *full-width* run of
white rows at the very end of the frame.
"""

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.pipeline.geometry import mm_to_px, px_to_mm

logger = logging.getLogger(__name__)

WORK_DPI = 75  # the box search runs on a copy downsampled to about this resolution
TAIL_WHITE_LEVEL = 250  # grey level (0-255) counted as scanner-white
TAIL_ROW_FRACTION = 0.98  # share of a row that must be white for it to belong to the tail
BG_SAMPLE_NEAR_MM = 3.0  # background is sampled between these distances from each side edge
BG_SAMPLE_FAR_MM = 8.0
FOREGROUND_DISTANCE = 40.0  # Euclidean RGB distance from the background that counts as photo
OPEN_KERNEL_MM = 3.0  # opening removes the thin white edge strip and speckle noise
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
    """A detected photo box plus whether its size is believable for a photo print."""

    box: Box
    plausible: bool


def detect_photo(frame: np.ndarray, dpi: float) -> Detection:
    """Locate the photo in a raw RGB frame: its bounding box plus a size check."""
    raise NotImplementedError


def _validate_frame(frame: np.ndarray) -> None:
    if frame.dtype != np.uint8 or frame.ndim != RGB_CHANNELS or frame.shape[2] != RGB_CHANNELS:
        raise ValueError(
            f"frame must be an HxWx3 uint8 RGB array, got {frame.dtype} with shape {frame.shape}"
        )


def _downsample(frame: np.ndarray, dpi: float) -> tuple[np.ndarray, int]:
    factor = max(1, round(dpi / WORK_DPI))
    height, width = frame.shape[:2]
    small = cv2.resize(
        np.ascontiguousarray(frame),
        (max(1, width // factor), max(1, height // factor)),
        interpolation=cv2.INTER_AREA,
    )
    return small, factor


def _tail_start(small: np.ndarray) -> int:
    """First row of the trailing run of (almost) fully white rows, or the frame height."""
    grey = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    white_rows = (grey >= TAIL_WHITE_LEVEL).mean(axis=1) >= TAIL_ROW_FRACTION
    content_rows = np.flatnonzero(~white_rows)
    return int(content_rows[-1]) + 1 if content_rows.size else grey.shape[0]


def _background_colour(content: np.ndarray, work_dpi: float) -> np.ndarray:
    near = mm_to_px(BG_SAMPLE_NEAR_MM, work_dpi)
    far = max(near + 1, mm_to_px(BG_SAMPLE_FAR_MM, work_dpi))
    if content.shape[1] <= 2 * far:
        raise ValueError(f"frame is too narrow to sample the background: {content.shape[1]} px")
    band = np.concatenate(
        [content[:, near:far].reshape(-1, 3), content[:, -far:-near].reshape(-1, 3)]
    )
    return np.median(band, axis=0).astype(np.float32)


def _foreground_mask(content: np.ndarray, work_dpi: float) -> np.ndarray:
    """Pixels far from the background colour, with thin edge strips and speckle removed."""
    background = _background_colour(content, work_dpi)
    distance = np.linalg.norm(content.astype(np.float32) - background, axis=2)
    side = max(1, mm_to_px(OPEN_KERNEL_MM, work_dpi))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (side, side))
    mask = (distance > FOREGROUND_DISTANCE).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)


def _largest_component(mask: np.ndarray) -> tuple[int, int, int, int]:
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        raise NoPhotoFoundError("no region differs from the scanner background")
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(v) for v in stats[best, :4])
    return x, y, w, h


def find_photo_box(frame: np.ndarray, dpi: float) -> Box:
    """Locate the photo in a raw RGB frame and return its bounding box in frame pixels.

    Raises ``NoPhotoFoundError`` when nothing photo-sized stands out from the background and
    ``ValueError`` for malformed input. ``frame`` is never modified.
    """
    _validate_frame(frame)
    small, factor = _downsample(frame, dpi)
    work_dpi = dpi / factor
    mask = _foreground_mask(small[: _tail_start(small)], work_dpi)
    sx, sy, sw, sh = _largest_component(mask)
    frame_h, frame_w = frame.shape[:2]
    x0, y0 = sx * factor, sy * factor
    x1, y1 = min((sx + sw) * factor, frame_w), min((sy + sh) * factor, frame_h)
    box = Box(x0, y0, x1 - x0, y1 - y0)
    _check_plausible(box, frame_w, frame_h, dpi)
    return box


def _check_plausible(box: Box, frame_w: int, frame_h: int, dpi: float) -> None:
    minimum = mm_to_px(MIN_PHOTO_MM, dpi)
    if box.w < minimum or box.h < minimum:
        w_mm, h_mm = box.mm(dpi)[2:]
        raise NoPhotoFoundError(
            f"largest region is {w_mm:.1f}x{h_mm:.1f} mm, below the {MIN_PHOTO_MM:g} mm minimum"
        )
    if box.x == 0 or box.y == 0 or box.x + box.w >= frame_w or box.y + box.h >= frame_h:
        logger.warning("photo box touches the frame edge; the photo may be cut off")


def crop(frame: np.ndarray, box: Box) -> np.ndarray:
    """Return a copy of ``frame`` restricted to ``box``."""
    height, width = frame.shape[:2]
    if box.x < 0 or box.y < 0 or box.x + box.w > width or box.y + box.h > height:
        raise ValueError(f"box {box} lies outside the {width}x{height} frame")
    return frame[box.y : box.y + box.h, box.x : box.x + box.w].copy()
