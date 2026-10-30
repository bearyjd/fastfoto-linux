"""Red-eye suggestions, manual ellipses and source-based RGB rendering."""

import hashlib
import io
import math
from pathlib import Path
from threading import Event

import numpy as np
from PIL import Image

from fastfoto_linux.documents.private_io import ensure_private_dir, write_private_atomic
from fastfoto_linux.enhance import redeye
from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.photo_edits.color import apply_white_balance
from fastfoto_linux.photo_edits.detail import apply_denoise, apply_sharpen
from fastfoto_linux.photo_edits.geometry import apply_geometry
from fastfoto_linux.photo_edits.model import (
    MAX_MASK_PIXELS,
    PREVIEW_MAX_PX,
    EyeEdit,
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoSource,
    PhotoTone,
    check_cancel,
    finite,
    integer,
)
from fastfoto_linux.photo_edits.results import PhotoPreview

GAUSS_SUPPORT_SIGMAS = 4
MIN_PADDING_PX = 2
PREVIEW_QUALITY = 90
TONE_TILE_PIXELS = 262_144
RGB_MAX = 255
CONTROL_SCALE = 100
BRIGHTNESS_SCALE = 200
RGB_MIDPOINT = 0.5
GRAY_WEIGHTS = (0.2126, 0.7152, 0.0722)


def _tone_tile(pixels: np.ndarray, tone: PhotoTone) -> np.ndarray:
    """Transform one contiguous RGB tile in float64, clipping only at conversion."""
    original = pixels.astype(np.float64) / RGB_MAX
    adjusted = (original + tone.brightness / BRIGHTNESS_SCALE - RGB_MIDPOINT) * (
        1 + tone.contrast / CONTROL_SCALE
    ) + RGB_MIDPOINT
    gray = (
        GRAY_WEIGHTS[0] * adjusted[:, 0]
        + GRAY_WEIGHTS[1] * adjusted[:, 1]
        + GRAY_WEIGHTS[2] * adjusted[:, 2]
    )[:, np.newaxis]
    saturated = gray + (adjusted - gray) * (1 + tone.saturation / CONTROL_SCALE)
    mixed = original + (tone.strength / CONTROL_SCALE) * (saturated - original)
    return np.floor(RGB_MAX * np.clip(mixed, 0, 1) + RGB_MIDPOINT).astype(np.uint8)


def _apply_tone(pixels: np.ndarray, tone: PhotoTone, cancel: Event) -> None:
    if tone.strength == 0 or (tone.brightness, tone.contrast, tone.saturation) == (0, 0, 0):
        return
    flat = pixels.reshape(-1, 3)
    for start in range(0, len(flat), TONE_TILE_PIXELS):
        check_cancel(cancel)
        tile = flat[start : start + TONE_TILE_PIXELS]
        tile[:] = _tone_tile(tile, tone)


def _apply_color(pixels: np.ndarray, recipe: PhotoEditRecipe, dpi: float, cancel: Event) -> None:
    """The post stage, in place on an owned buffer: white balance, tone, then sharpen."""
    apply_white_balance(pixels, recipe.white_balance, cancel)
    _apply_tone(pixels, recipe.tone, cancel)
    apply_sharpen(pixels, recipe.detail, dpi, cancel)


def detect_eyes(
    source: PhotoSource, *, cancel: Event, detector: FaceDetector | None = None
) -> tuple[EyeEdit, ...]:
    """Return pending suggestions using the existing full-resolution detection gates."""
    check_cancel(cancel)
    fixes = redeye.detect_fixes(source.pixels, source.effective_dpi, detector)
    check_cancel(cancel)
    return tuple(
        EyeEdit(f"detected-{index + 1}", "detected", fix.roi, fix.center, fix.mask)
        for index, fix in enumerate(fixes)
    )


def manual_eye(  # noqa: PLR0913 - the explicit source-space ellipse is the public contract
    source: PhotoSource,
    *,
    eye_id: str,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    strength: int = 100,
) -> EyeEdit:
    """An accepted manual pupil mask, clipped to the retained original."""
    cx, cy, rx, ry = (finite(value, "ellipse coordinate") for value in (cx, cy, rx, ry))
    if rx <= 0 or ry <= 0 or not 0 <= cx < source.width or not 0 <= cy < source.height:
        raise PhotoEditError("ellipse needs positive radii and a center inside the source")
    reach = max(rx, ry)
    padding = max(
        MIN_PADDING_PX,
        math.ceil(reach * (redeye.GROW_FRACTION + redeye.FEATHER_FRACTION * GAUSS_SUPPORT_SIGMAS)),
    )
    x0, y0 = max(0, math.floor(cx - rx - padding)), max(0, math.floor(cy - ry - padding))
    x1 = min(source.width, math.ceil(cx + rx + padding) + 1)
    y1 = min(source.height, math.ceil(cy + ry + padding) + 1)
    if (x1 - x0) * (y1 - y0) > MAX_MASK_PIXELS:
        raise PhotoEditError("manual ellipse is too large")
    ys, xs = np.ogrid[y0:y1, x0:x1]
    mask = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 <= 1
    return EyeEdit(eye_id, "manual", (x0, y0, x1, y1), (cx, cy), mask, True, strength)


def _same_source(source: PhotoSource, recipe: PhotoEditRecipe) -> None:
    other = recipe.source
    identity = ("sha256", "byte_size", "width", "height", "orientation", "dpi_x", "dpi_y")
    if source.path != other.path or any(
        getattr(source, key) != getattr(other, key) for key in identity
    ):
        raise PhotoEditError("recipe source identity does not match the retained source")


def _overlap(left: EyeEdit, right: EyeEdit) -> bool:
    ax, ay, ar, ab = left.roi
    bx, by, br, bb = right.roi
    return ax < br and bx < ar and ay < bb and by < ab


def _eye_buffer(source: PhotoSource, recipe: PhotoEditRecipe, cancel: Event) -> np.ndarray:
    """A copy of the source with the accepted eye corrections applied, in source space."""
    check_cancel(cancel)
    _same_source(source, recipe)
    accepted = tuple(edit for edit in recipe.eyes if edit.accepted)
    for index, edit in enumerate(accepted):
        if any(_overlap(edit, other) for other in accepted[:index]):
            raise PhotoEditError("accepted eye regions overlap; resize or reject the duplicate")
    result = source.pixels.copy()
    for edit in accepted:
        check_cancel(cancel)
        x0, y0, x1, y1 = edit.roi
        center = (edit.center[0] - x0, edit.center[1] - y0)
        fix = redeye.EyeFix((0, 0, x1 - x0, y1 - y0), edit.mask, center)
        result[y0:y1, x0:x1] = redeye.apply_fixes(
            source.pixels[y0:y1, x0:x1], (fix,), strength=edit.strength / 100
        )
    check_cancel(cancel)
    return result


def _pre_stage(source: PhotoSource, recipe: PhotoEditRecipe, cancel: Event) -> np.ndarray:
    """The source-space buffer: eye corrections, then denoise, before any resampling."""
    buffer = _eye_buffer(source, recipe, cancel)
    apply_denoise(buffer, recipe.detail, cancel)
    return buffer


def render(source: PhotoSource, recipe: PhotoEditRecipe, *, cancel: Event) -> np.ndarray:
    """Render eyes, denoise, straighten, crop, turn, white balance, tone, then sharpen.

    The source is untouched. Sharpen is last because it does not commute with resampling or crop.
    """
    result = _pre_stage(source, recipe, cancel)
    if recipe.geometry != PhotoGeometry():
        result = apply_geometry(result, recipe.geometry, cancel=cancel)
        check_cancel(cancel)
    _apply_color(result, recipe, source.effective_dpi, cancel)
    check_cancel(cancel)
    return result


def _preview_jpeg(
    pixels: np.ndarray, *, bounded: bool, icc_profile: bytes | None
) -> tuple[bytes, tuple[int, int]]:
    image = Image.fromarray(pixels)
    if bounded:
        image.thumbnail((PREVIEW_MAX_PX, PREVIEW_MAX_PX))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=PREVIEW_QUALITY, subsampling=0, icc_profile=icc_profile)
    return buffer.getvalue(), image.size


def _roi_blobs(
    source: PhotoSource, recipe: PhotoEditRecipe, selected_id: str, working: np.ndarray
) -> list[bytes]:
    selected = next((eye for eye in recipe.eyes if eye.id == selected_id), None)
    if selected is None:
        raise PhotoEditError("selected eye is no longer in the draft")
    x0, y0, x1, y1 = selected.roi
    return [
        _preview_jpeg(pixels[y0:y1, x0:x1], bounded=False, icc_profile=source.icc_profile)[0]
        for pixels in (source.pixels, working)
    ]


def _straightened_images(
    source: PhotoSource, recipe: PhotoEditRecipe, selected_id: str | None, cancel: Event
) -> tuple[list[bytes], tuple[int, int]]:
    """Blobs for an angled draft, keeping at most the eye buffer and one warped buffer alive."""
    icc = source.icc_profile
    buffer = _pre_stage(source, recipe, cancel)
    # Colour follows every warp, as in render(); the levelled frame is warped before its colour.
    level = PhotoGeometry(straighten_tenths=recipe.geometry.straighten_tenths)
    frame = apply_geometry(buffer, level, cancel=cancel)
    _apply_color(frame, recipe, source.effective_dpi, cancel)
    frame_blob, _ = _preview_jpeg(frame, bounded=True, icc_profile=icc)
    del frame
    after = apply_geometry(buffer, recipe.geometry, cancel=cancel)
    _apply_color(after, recipe, source.effective_dpi, cancel)
    after_blob, size = _preview_jpeg(after, bounded=True, icc_profile=icc)
    del after
    _apply_color(buffer, recipe, source.effective_dpi, cancel)
    before_blob, _ = _preview_jpeg(source.pixels, bounded=True, icc_profile=icc)
    working_blob, _ = _preview_jpeg(buffer, bounded=True, icc_profile=icc)
    blobs = [before_blob, after_blob, working_blob]
    if selected_id is not None:
        blobs += _roi_blobs(source, recipe, selected_id, buffer)
    blobs.append(frame_blob)
    return blobs, size


def _preview_images(
    source: PhotoSource, recipe: PhotoEditRecipe, selected_id: str | None, cancel: Event
) -> tuple[list[bytes], tuple[int, int]]:
    """Blobs: before, after, working, [roi_before, roi_after], and straightened last if angled."""
    if recipe.geometry.straighten_tenths:
        return _straightened_images(source, recipe, selected_id, cancel)
    dpi, icc = source.effective_dpi, source.icc_profile
    working = _pre_stage(source, recipe, cancel)
    after = None
    if recipe.geometry != PhotoGeometry():
        # Sharpen does not commute with crop: run the post stage on the cropped buffer.
        after = apply_geometry(working, recipe.geometry, cancel=cancel)
        _apply_color(after, recipe, dpi, cancel)
    _apply_color(working, recipe, dpi, cancel)
    before_blob, _ = _preview_jpeg(source.pixels, bounded=True, icc_profile=icc)
    working_blob, size = _preview_jpeg(working, bounded=True, icc_profile=icc)
    after_blob = working_blob
    if after is not None:
        after_blob, size = _preview_jpeg(after, bounded=True, icc_profile=icc)
    blobs = [before_blob, after_blob, working_blob]
    if selected_id is not None:
        blobs += _roi_blobs(source, recipe, selected_id, working)
    return blobs, size


def make_preview(  # noqa: PLR0913 - preview geometry and cancellation are explicit
    source: PhotoSource,
    recipe: PhotoEditRecipe,
    *,
    cache_dir: Path,
    generation: int,
    cancel: Event,
    selected_id: str | None = None,
) -> PhotoPreview:
    """Publish private bounded previews, with an optional full-resolution eye crop."""
    check_cancel(cancel)
    integer(generation, 0, 2**63 - 1, "preview generation")
    blobs, size = _preview_images(source, recipe, selected_id, cancel)
    check_cancel(cancel)
    cache_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    ensure_private_dir(cache_dir)
    token = hashlib.sha256(b"".join(blobs)).hexdigest()[:24]
    paths = [
        cache_dir / f"{source.sha256[:16]}-{generation}-{token}-{n}.jpg" for n in range(len(blobs))
    ]
    published: list[Path] = []
    try:
        for path, blob in zip(paths, blobs, strict=True):
            write_private_atomic(path, blob)
            published.append(path)
    except BaseException:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    return PhotoPreview(
        paths[0],
        paths[1],
        source.width,
        source.height,
        *size,
        source.sha256,
        generation,
        paths[3] if selected_id is not None else None,
        paths[4] if selected_id is not None else None,
        working=paths[2],
        straightened=paths[-1] if recipe.geometry.straighten_tenths else None,
    )
