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
# The tail is the last run of at least TAIL_MIN_MM white rows. Non-white gaps up to TAIL_GAP_MM
# (dirt streaks) do not break it; the real grey band under the paper is 9 mm or more, so it does.
TAIL_MIN_MM = 20.0
TAIL_GAP_MM = 8.5
BACKGROUND_PRIOR_RGB = (202.0, 210.0, 219.0)  # measured scanner background (blue-grey, B > R)
# Background samples come from between BG_SAMPLE_NEAR_MM and BG_SAMPLE_FAR_MM in from each side
# edge (the first millimetres glow brighter on real frames) and must lie this close (RGB
# distance) to the prior. If too few do, a looser pass accepts blue-grey (B >= R) pixels
# within BACKGROUND_FALLBACK_TOLERANCE, for a scanner with a differently tinted lamp or glass.
# Failing that the prior itself is used. Cream paper has R > B, so it never counts as background.
BG_SAMPLE_NEAR_MM = 3.0
BG_SAMPLE_FAR_MM = 8.0
BACKGROUND_PRIOR_TOLERANCE = 20.0
BACKGROUND_FALLBACK_TOLERANCE = 40.0
BACKGROUND_MIN_SAMPLES = 200
FOREGROUND_DISTANCE = 40.0  # RGB distance from the background that counts as photo
# Second pass for cream or aged backs, run when the first finds nothing or an implausible box. It
# also picks up the soft shadow some prints cast, so its boxes can be 2-7 mm too large.
PALE_FOREGROUND_DISTANCE = 20.0
OPEN_KERNEL_MM = 3.0  # opening removes the thin white edge strip, hairs and speckle noise
MIN_PHOTO_MM = 25.0  # smaller boxes are noise, not photos
FULL_WIDTH_SHARE = 0.95  # an implausible box this wide is the frame, not a photo
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
    """First row of the last long run of white rows; ``white_rows.size`` if there is none.

    Runs are white rows separated by non-white gaps of at most ``TAIL_GAP_MM``. The run need not
    reach the frame end, so a dirty trailing row does not matter.
    """
    max_gap = mm_to_px(TAIL_GAP_MM, work_dpi)
    min_rows = mm_to_px(TAIL_MIN_MM, work_dpi)
    white = np.flatnonzero(white_rows)
    if white.size == 0:
        return white_rows.size
    breaks = np.flatnonzero(np.diff(white) - 1 > max_gap) + 1
    run_starts = np.r_[0, breaks]
    run_sizes = np.diff(np.r_[run_starts, white.size])
    long_runs = np.flatnonzero(run_sizes >= min_rows)
    return int(white[run_starts[long_runs[-1]]]) if long_runs.size else white_rows.size


def _background_colour(small: np.ndarray, work_dpi: float) -> np.ndarray:
    """Median colour of side-band pixels that look like scanner background, else the prior."""
    near = mm_to_px(BG_SAMPLE_NEAR_MM, work_dpi)
    far = max(near + 1, mm_to_px(BG_SAMPLE_FAR_MM, work_dpi))
    width = small.shape[1]
    if width <= 2 * far:
        raise ValueError(f"frame is too narrow to sample the background: {width} px")
    pixels = small[:, np.r_[near:far, width - far : width - near]].reshape(-1, RGB_CHANNELS)
    offset = pixels.astype(np.float32) - np.asarray(BACKGROUND_PRIOR_RGB, dtype=np.float32)
    distance = np.linalg.norm(offset, axis=1)
    bluish = pixels[:, 2] >= pixels[:, 0]
    for source, chosen in (
        ("prior", distance <= BACKGROUND_PRIOR_TOLERANCE),
        ("fallback", (distance <= BACKGROUND_FALLBACK_TOLERANCE) & bluish),
    ):
        samples = pixels[chosen]
        if samples.shape[0] >= BACKGROUND_MIN_SAMPLES:
            background = np.median(samples, axis=0).astype(np.float32)
            logger.debug(
                "%s background %s from %d samples", source, background.tolist(), len(samples)
            )
            return background
    logger.debug("too few background samples; using the prior colour")
    return np.asarray(BACKGROUND_PRIOR_RGB, dtype=np.float32)


def _foreground_mask(
    distance: np.ndarray, threshold: float, tail_start: int, work_dpi: float
) -> np.ndarray:
    """Pixels farther than ``threshold`` from the background, minus the tail, strips and speckle."""
    mask = (distance > threshold).astype(np.uint8)
    mask[tail_start:] = 0
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


@dataclass(frozen=True)
class _Scan:
    """What the detection passes share: the distance map, the tail and the frame geometry."""

    distance: np.ndarray
    tail_start: int
    small_shape: tuple[int, ...]
    frame_shape: tuple[int, ...]
    factor: int
    dpi: float

    @property
    def work_dpi(self) -> float:
        return self.dpi / self.factor


@dataclass(frozen=True)
class _Hit:
    """The outcome of one pass: the box, where it sits on the work grid, and its plausibility."""

    box: Box
    work_box: tuple[int, int, int, int]
    others: int
    plausible: bool


def _prepare(frame: np.ndarray, dpi: float) -> _Scan:
    _validate_frame(frame)
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")
    small, factor = _downsample(frame, dpi)
    work_dpi = dpi / factor
    grey = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    white_rows = (grey >= TAIL_WHITE_LEVEL).mean(axis=1) >= TAIL_ROW_FRACTION
    background = _background_colour(small, work_dpi)
    distance = np.linalg.norm(small.astype(np.float32) - background, axis=2)
    tail_start = _tail_from(white_rows, work_dpi)
    return _Scan(distance, tail_start, small.shape, frame.shape, factor, dpi)


def _attempt(scan: _Scan, threshold: float) -> _Hit:
    """Find the largest region farther than ``threshold`` from the background."""
    mask = _foreground_mask(scan.distance, threshold, scan.tail_start, scan.work_dpi)
    x, y, w, h, others = _largest_component(mask, scan.work_dpi)
    box = _to_frame_box((x, y, w, h), scan.small_shape, scan.frame_shape, scan.factor)
    _require_photo_sized(box, scan.dpi)
    plausible = is_common_print_size(*box.mm(scan.dpi)[2:])
    if not plausible and box.w >= FULL_WIDTH_SHARE * scan.frame_shape[1]:
        raise NoPhotoFoundError(
            f"a {box.mm(scan.dpi)[2]:.0f} mm wide region spans the frame and matches no print size"
        )
    return _Hit(box, (x, y, w, h), others, plausible)


def detect_photo(frame: np.ndarray, dpi: float) -> Detection:
    """Locate the photo in a raw RGB frame: its bounding box in frame pixels plus a size check.

    A strict pass runs first; a more sensitive pass (cream or aged backs) runs when the strict
    one finds nothing or a box that matches no print size, and its box is used if it is plausible.
    Raises ``NoPhotoFoundError`` when nothing photo-sized stands out from the background (or the
    only candidate is the whole frame width) and ``ValueError`` for malformed input. ``frame`` is
    never modified. Logs a warning when the box touches the left, right or bottom frame edge (the
    top edge is normal for ADF scans), when a second photo-sized region was ignored, or when the
    size is implausible for a print.
    """
    scan = _prepare(frame, dpi)
    failure = NoPhotoFoundError("no region differs from the scanner background")
    implausible: _Hit | None = None
    for threshold in (FOREGROUND_DISTANCE, PALE_FOREGROUND_DISTANCE):
        try:
            hit = _attempt(scan, threshold)
        except NoPhotoFoundError as error:
            logger.debug("no photo at distance threshold %g: %s", threshold, error)
            failure = error
            continue
        if hit.plausible:
            return _report(hit, scan)
        implausible = implausible or hit
    if implausible is None:
        raise failure
    return _report(implausible, scan)


def find_photo_box(frame: np.ndarray, dpi: float) -> Box:
    """Like :func:`detect_photo` but returns only the box; implausible sizes still log a warning."""
    return detect_photo(frame, dpi).box


def _report(hit: _Hit, scan: _Scan) -> Detection:
    _report_edges(hit.work_box, scan.small_shape)
    if hit.others:
        logger.warning(
            "ignored %d other photo-sized region(s); only the largest is returned", hit.others
        )
    if not hit.plausible:
        w_mm, h_mm = hit.box.mm(scan.dpi)[2:]
        logger.warning(
            "box %.0fx%.0f mm matches no common print size; part of the photo may be close to the "
            "scanner background colour (sky, pale border) or a stamp was found instead of the "
            "paper",
            w_mm,
            h_mm,
        )
    return Detection(hit.box, hit.plausible)


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


def crop(frame: np.ndarray, box: Box) -> np.ndarray:
    """Return a copy of ``frame`` restricted to ``box``."""
    _validate_frame(frame)
    height, width = frame.shape[:2]
    if box.x < 0 or box.y < 0 or box.x + box.w > width or box.y + box.h > height:
        raise ValueError(f"box {box} lies outside the {width}x{height} frame")
    return frame[box.y : box.y + box.h, box.x : box.x + box.w].copy()
