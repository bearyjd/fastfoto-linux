"""Exact crop and clockwise quarter-turn, optionally fused with a fixed-point straighten warp."""

from threading import Event

import numpy as np

from fastfoto_linux.photo_edits import straighten
from fastfoto_linux.photo_edits.model import (
    PhotoEditCancelledError,
    PhotoGeometry,
    PhotoSource,
    frame_size,
)


def _turn_back(r: np.ndarray, c: np.ndarray, quarter_turns: int, size: tuple[int, int]):
    """Map output (row, col) back to crop-frame (row, col) through the inverse turn."""
    crop_w, crop_h = size
    if quarter_turns == 0:
        return r, c
    if quarter_turns == 1:
        return crop_h - 1 - c, r
    if quarter_turns == 2:  # noqa: PLR2004
        return crop_h - 1 - r, crop_w - 1 - c
    return c, crop_w - 1 - r


def _warp_fused(pixels: np.ndarray, geometry: PhotoGeometry, cancel: Event | None) -> np.ndarray:
    """Straighten, crop and turn in one pass, tile by tile, straight into the final layout."""
    height, width = pixels.shape[:2]
    tenths, turns = geometry.straighten_tenths, geometry.quarter_turns
    frame_w, frame_h = straighten.straightened_size(width, height, tenths)
    left, top, right, bottom = geometry.crop or (0, 0, frame_w, frame_h)
    crop_w, crop_h = right - left, bottom - top
    out_h, out_w = (crop_w, crop_h) if turns % 2 else (crop_h, crop_w)
    result = np.empty((out_h, out_w, 3), dtype=np.uint8)
    tile = straighten.TILE
    for r0 in range(0, out_h, tile):
        for c0 in range(0, out_w, tile):
            if cancel is not None and cancel.is_set():
                raise PhotoEditCancelledError("photo edit cancelled")
            r1, c1 = min(r0 + tile, out_h), min(c0 + tile, out_w)
            r = np.arange(r0, r1, dtype=np.int64)[:, np.newaxis]
            c = np.arange(c0, c1, dtype=np.int64)[np.newaxis, :]
            crop_r, crop_c = _turn_back(r, c, turns, (crop_w, crop_h))
            x, y = straighten.sample_coords(
                width, height, frame_w, frame_h, tenths, left + crop_c, top + crop_r
            )
            result[r0:r1, c0:c1] = straighten.warp_tile(pixels, x, y)
    return result


def apply_geometry(
    pixels: np.ndarray, geometry: PhotoGeometry, *, cancel: Event | None = None
) -> np.ndarray:
    """Straighten, crop in that frame, then turn clockwise; always a new C-contiguous array."""
    if geometry.straighten_tenths:
        return _warp_fused(pixels, geometry, cancel)
    height, width = pixels.shape[:2]
    left, top, right, bottom = geometry.crop or (0, 0, width, height)
    turned = np.rot90(pixels[top:bottom, left:right], k=-geometry.quarter_turns)
    return np.array(turned, dtype=np.uint8, order="C", copy=True)


def output_size(source: PhotoSource, geometry: PhotoGeometry) -> tuple[int, int]:
    """The (width, height) a recipe with this geometry produces."""
    left, top, right, bottom = geometry.crop or (0, 0, *frame_size(source, geometry))
    width, height = right - left, bottom - top
    return (height, width) if geometry.quarter_turns % 2 else (width, height)
