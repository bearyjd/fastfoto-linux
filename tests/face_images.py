"""Synthetic "photos" built around the public-domain astronaut portrait (tests/fixtures)."""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ASTRONAUT = Path(__file__).parent / "fixtures" / "astronaut.jpg"
TEXTURE_BLUR_SIGMA = 6


def load_astronaut() -> np.ndarray:
    with Image.open(ASTRONAUT) as image:
        return np.array(image.convert("RGB"))


def gradient_background(height: int, width: int, seed: int = 0) -> np.ndarray:
    """A smooth coloured gradient with mild noise, deterministic for a given seed."""
    rng = np.random.default_rng(seed)
    rows, cols = np.mgrid[0:height, 0:width]
    background = np.zeros((height, width, 3), dtype=int)
    background[..., 0] = 40 + 90 * cols / width
    background[..., 1] = 90 + 60 * rows / height
    background[..., 2] = 130
    noisy = background + rng.integers(-8, 8, background.shape)
    return np.clip(noisy, 0, 255).astype(np.uint8)


def scaled_face(scale: int) -> np.ndarray:
    face = load_astronaut()
    if scale == 1:
        return face
    return cv2.resize(face, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def photo_with_face(height: int, width: int, scale: int, top_left: tuple[int, int]) -> np.ndarray:
    """The upright portrait pasted (at ``scale``) onto a gradient background."""
    photo = gradient_background(height, width)
    face = scaled_face(scale)
    row, col = top_left
    photo[row : row + face.shape[0], col : col + face.shape[1]] = face
    return photo


def photo_with_two_faces(height: int, width: int) -> np.ndarray:
    """One upright face on the left and the same face turned 90 degrees on the right.

    Rotating the whole image makes exactly one of the two faces upright, so neither rotation
    is clearly better than the other.
    """
    photo = gradient_background(height, width)
    face = scaled_face(2)
    margin = 100
    size = face.shape[0]
    photo[margin : margin + size, margin : margin + size] = face
    turned = np.ascontiguousarray(np.rot90(face, 1))
    photo[margin : margin + size, width - margin - size : width - margin] = turned
    return photo


def textured_photo_without_faces(height: int, width: int) -> np.ndarray:
    rng = np.random.default_rng(1)
    noise = rng.integers(0, 255, (height, width, 3)).astype(np.uint8)
    return cv2.GaussianBlur(noise, (0, 0), TEXTURE_BLUR_SIGMA)
