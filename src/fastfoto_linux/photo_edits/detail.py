"""Banded luma/chroma noise reduction and luminance sharpening on owned RGB buffers."""

import math
from collections.abc import Callable
from threading import Event

import cv2
import numpy as np

from fastfoto_linux.photo_edits.model import PhotoDetail, PhotoEditError, check_cancel

NLM_TEMPLATE = 7
NLM_SEARCH = 15
DENOISE_HALO = NLM_TEMPLATE // 2 + NLM_SEARCH // 2
H_LUMA_MAX = 10.0
H_CHROMA_MAX = 15.0
DETAIL_BAND_PIXELS = 1_048_576
SHARPEN_AMOUNT_MAX = 1.5
SHARPEN_REFERENCE_DPI = 300.0
SHARPEN_SIGMA_MIN = 0.5
SHARPEN_SIGMA_MAX = 3.0
SIGMA_SUPPORT = 3
CONTROL_SCALE = 100
RGB_MAX = 255
ROUND_HALF = 0.5
MIN_BAND_HALOS = 4
GRAY_WEIGHTS = (0.2126, 0.7152, 0.0722)
# OpenCV's inverse YCrCb matrix, applied to the denoise deltas only.
CR_TO_R, CR_TO_G, CB_TO_G, CB_TO_B = 1.403, -0.714, -0.344, 1.773

Kernel = Callable[[np.ndarray], np.ndarray]
F32 = np.float32


def _round_uint8(values: np.ndarray) -> np.ndarray:
    return np.floor(np.clip(values, 0, RGB_MAX) + F32(ROUND_HALF)).astype(np.uint8)


def _bands(pixels: np.ndarray, halo: int, kernel: Kernel, cancel: Event) -> None:
    """Filter full-width row bands in place; each sees `halo` original rows on both sides."""
    if not pixels.flags.c_contiguous:
        raise PhotoEditError("detail needs a contiguous RGB buffer")
    height, width = pixels.shape[:2]
    step = max(MIN_BAND_HALOS * halo, DETAIL_BAND_PIXELS // width)
    carry = pixels[:0].copy()
    for start in range(0, height, step):
        check_cancel(cancel)
        stop = min(start + step, height)
        below = pixels[stop : min(stop + halo, height)]
        out = kernel(np.concatenate((carry, pixels[start:stop], below)))
        carry = pixels[max(stop - halo, start) : stop].copy()
        pixels[start:stop] = out[len(out) - len(below) - (stop - start) : len(out) - len(below)]


def _denoise_kernel(detail: PhotoDetail) -> Kernel:
    def kernel(chunk: np.ndarray) -> np.ndarray:
        ycc = cv2.cvtColor(chunk, cv2.COLOR_RGB2YCrCb)
        zero = np.zeros(chunk.shape[:2], dtype=np.int16)
        d_y, d_cr, d_cb = zero, zero, zero
        if detail.denoise_luma:
            h = H_LUMA_MAX * detail.denoise_luma / CONTROL_SCALE
            plane = np.ascontiguousarray(ycc[..., 0])
            d_y = cv2.fastNlMeansDenoising(plane, None, h, NLM_TEMPLATE, NLM_SEARCH).astype(
                np.int16
            ) - plane.astype(np.int16)
        if detail.denoise_chroma:
            h = H_CHROMA_MAX * detail.denoise_chroma / CONTROL_SCALE
            planes = np.ascontiguousarray(ycc[..., 1:3])
            d_c = cv2.fastNlMeansDenoising(planes, None, h, NLM_TEMPLATE, NLM_SEARCH).astype(
                np.int16
            ) - planes.astype(np.int16)
            d_cr, d_cb = d_c[..., 0], d_c[..., 1]
        y, cr, cb = (delta.astype(F32) for delta in (d_y, d_cr, d_cb))
        red = chunk[..., 0].astype(F32) + y + F32(CR_TO_R) * cr
        green = chunk[..., 1].astype(F32) + y + F32(CR_TO_G) * cr + F32(CB_TO_G) * cb
        blue = chunk[..., 2].astype(F32) + y + F32(CB_TO_B) * cb
        return _round_uint8(np.stack([red, green, blue], axis=-1))

    return kernel


def sharpen_window(dpi: float) -> tuple[float, int]:
    """The Gaussian sigma and odd kernel size for a scan resolution."""
    sigma = min(SHARPEN_SIGMA_MAX, max(SHARPEN_SIGMA_MIN, dpi / SHARPEN_REFERENCE_DPI))
    return sigma, 2 * math.ceil(SIGMA_SUPPORT * sigma) + 1


def _sharpen_kernel(detail: PhotoDetail, dpi: float) -> Kernel:
    sigma, ksize = sharpen_window(dpi)
    amount = F32(SHARPEN_AMOUNT_MAX * detail.sharpen / CONTROL_SCALE)

    def kernel(chunk: np.ndarray) -> np.ndarray:
        luma = (
            F32(GRAY_WEIGHTS[0]) * chunk[..., 0].astype(F32)
            + F32(GRAY_WEIGHTS[1]) * chunk[..., 1].astype(F32)
            + F32(GRAY_WEIGHTS[2]) * chunk[..., 2].astype(F32)
        )
        blur = cv2.GaussianBlur(luma, (ksize, ksize), sigma, borderType=cv2.BORDER_REFLECT_101)
        return _round_uint8(chunk.astype(F32) + (amount * (luma - blur))[..., np.newaxis])

    return kernel


def apply_denoise(pixels: np.ndarray, detail: PhotoDetail, cancel: Event) -> None:
    """Reduce luma and chroma noise in place; returns at once when both strengths are 0."""
    if not (detail.denoise_luma or detail.denoise_chroma):
        return
    _bands(pixels, DENOISE_HALO, _denoise_kernel(detail), cancel)
    check_cancel(cancel)


def apply_sharpen(pixels: np.ndarray, detail: PhotoDetail, dpi: float, cancel: Event) -> None:
    """Unsharp-mask the luminance in place; returns at once when the strength is 0."""
    if not detail.sharpen:
        return
    _bands(pixels, sharpen_window(dpi)[1] // 2, _sharpen_kernel(detail, dpi), cancel)
    check_cancel(cancel)
