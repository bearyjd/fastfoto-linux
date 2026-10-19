"""Generated images only; no scanner, downloaded corpus or private scans."""

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.photo_edits import EyeEdit, PhotoSource

WIDTH = 160
HEIGHT = 100
DPI = 300
LEFT = (48, 48)
RIGHT = (112, 48)
RADIUS = 5


def pixels() -> np.ndarray:
    image = np.full((HEIGHT, WIDTH, 3), (200, 150, 130), dtype=np.uint8)
    ys, xs = np.ogrid[:HEIGHT, :WIDTH]
    for cx, cy in (LEFT, RIGHT):
        image[(xs - cx) ** 2 + (ys - cy) ** 2 <= RADIUS**2] = (230, 20, 20)
    image[LEFT[1], LEFT[0]] = (255, 250, 250)
    return image


def source_at(folder: Path) -> PhotoSource:
    path = folder / "photo_0001.jpg"
    Image.fromarray(pixels()).save(path, quality=100, subsampling=0, dpi=(DPI, DPI))
    data = path.read_bytes()
    with Image.open(path) as image:
        decoded = np.array(image.convert("RGB"))
    decoded.setflags(write=False)
    return PhotoSource(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        width=WIDTH,
        height=HEIGHT,
        dpi_x=DPI,
        dpi_y=DPI,
        effective_dpi=DPI,
        pixels=decoded,
    )


def eye(
    eye_id: str = "left", *, accepted: bool = True, strength: int = 100, right: bool = False
) -> EyeEdit:
    cx, cy = RIGHT if right else LEFT
    half = 12
    ys, xs = np.ogrid[-half : half + 1, -half : half + 1]
    mask = xs**2 + ys**2 <= RADIUS**2
    return EyeEdit(
        id=eye_id,
        origin="manual",
        roi=(cx - half, cy - half, cx + half + 1, cy + half + 1),
        center=(cx, cy),
        mask=mask,
        accepted=accepted,
        strength=strength,
    )
