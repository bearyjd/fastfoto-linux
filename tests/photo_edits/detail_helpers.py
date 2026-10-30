"""Generated sources, a spy for the NLM calls and numpy references for the detail tests."""

import math
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from fastfoto_linux.photo_edits import PhotoDetail, PhotoEditRecipe, PhotoSource, update_detail
from tests.photo_edits.helpers import source_at

F32 = np.float32
Y_WEIGHTS = (0.2126, 0.7152, 0.0722)


def with_pixels(tmp_path: Path, pixels: np.ndarray, *, dpi: float = 300.0) -> PhotoSource:
    """The helper source carrying other generated pixels (identity hash is not re-derived)."""
    height, width = pixels.shape[:2]
    return replace(
        source_at(tmp_path),
        width=width,
        height=height,
        dpi_x=dpi,
        dpi_y=dpi,
        effective_dpi=dpi,
        pixels=pixels,
    )


def noisy_pixels(
    height: int = 64, width: int = 96, *, seed: int = 3, sigma: float = 8.0
) -> np.ndarray:
    """A flat patch with independent per-channel noise: luma and chroma grain."""
    rng = np.random.default_rng(seed)
    flat = np.full((height, width, 3), (128, 120, 110), dtype=np.float64)
    return np.clip(flat + rng.normal(0, sigma, flat.shape), 0, 255).round().astype(np.uint8)


def noisy_source(tmp_path: Path, *, dpi: float = 300.0, height: int = 64, width: int = 96):
    return with_pixels(tmp_path, noisy_pixels(height, width), dpi=dpi)


def flat_source(tmp_path: Path, color: tuple[int, int, int] = (120, 90, 60)) -> PhotoSource:
    return with_pixels(tmp_path, np.full((64, 96, 3), color, dtype=np.uint8))


def step_source(tmp_path: Path) -> PhotoSource:
    pixels = np.empty((64, 96, 3), dtype=np.uint8)
    pixels[:, :48] = (80, 100, 120)
    pixels[:, 48:] = (160, 170, 180)
    return with_pixels(tmp_path, pixels)


def with_detail(recipe: PhotoEditRecipe, luma: int, chroma: int, sharpen: int) -> PhotoEditRecipe:
    return update_detail(recipe, PhotoDetail(luma, chroma, sharpen))


def ycc(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)


def reconstruct(
    rgb: np.ndarray, luma_out: np.ndarray | None, chroma_out: np.ndarray | None
) -> np.ndarray:
    """The delta reconstruction from the design note, given the NLM outputs it consumed."""
    base = ycc(rgb).astype(np.int16)
    zero = np.zeros(rgb.shape[:2], dtype=np.int16)
    d_y = zero if luma_out is None else luma_out.astype(np.int16) - base[..., 0]
    d_cr = zero if chroma_out is None else chroma_out[..., 0].astype(np.int16) - base[..., 1]
    d_cb = zero if chroma_out is None else chroma_out[..., 1].astype(np.int16) - base[..., 2]
    y, cr, cb = (d.astype(F32) for d in (d_y, d_cr, d_cb))
    red, green, blue = (rgb[..., i].astype(F32) for i in range(3))
    red = red + y + F32(1.403) * cr
    green = green + y - F32(0.714) * cr - F32(0.344) * cb
    blue = blue + y + F32(1.773) * cb
    stacked = np.stack([red, green, blue], axis=-1)
    return np.floor(np.clip(stacked, 0, 255) + F32(0.5)).astype(np.uint8)


def reference_window(dpi: float) -> tuple[float, int]:
    """Sigma and kernel size from the design note: clamp(dpi / 300, 0.5, 3.0), 2*ceil(3 s)+1."""
    sigma = min(3.0, max(0.5, 1.0 * dpi / 300))
    return sigma, 2 * math.ceil(3 * sigma) + 1


def reference_sharpen(rgb: np.ndarray, strength: int, dpi: float) -> np.ndarray:
    sigma, ksize = reference_window(dpi)
    luma = (
        F32(Y_WEIGHTS[0]) * rgb[..., 0].astype(F32)
        + F32(Y_WEIGHTS[1]) * rgb[..., 1].astype(F32)
        + F32(Y_WEIGHTS[2]) * rgb[..., 2].astype(F32)
    )
    blur = cv2.GaussianBlur(luma, (ksize, ksize), sigma, borderType=cv2.BORDER_REFLECT_101)
    delta = F32(1.5 * strength / 100) * (luma - blur)
    return np.floor(np.clip(rgb.astype(F32) + delta[..., None], 0, 255) + F32(0.5)).astype(np.uint8)


class NlmSpy:
    """Stands in for the `cv2` name inside detail.py and records every NLM call."""

    def __init__(self, on_call=None) -> None:
        self.calls: list[tuple[tuple[int, ...], float, np.ndarray]] = []
        self._on_call = on_call

    def fastNlMeansDenoising(self, src, dst, h, template, search):
        out = cv2.fastNlMeansDenoising(src, dst, h, template, search)
        self.calls.append((src.shape, h, out.copy()))
        if self._on_call is not None:
            self._on_call(len(self.calls))
        return out

    def __getattr__(self, name: str):
        return getattr(cv2, name)


class Forbidden:
    """Any use of OpenCV through this name fails the test."""

    def __getattr__(self, name: str):
        raise AssertionError(f"the bypass must not touch cv2.{name}")
