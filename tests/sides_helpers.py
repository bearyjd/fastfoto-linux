"""Shared builders for the sides tests: cropped synthetic sides and in-memory page batches."""

from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from fastfoto_linux.pipeline.crop import Box
from tests.synth import make_frame

SIDES_LOGGER = "fastfoto_linux.pipeline.sides"
Sheet = tuple[tuple[np.ndarray, Box], tuple[np.ndarray, Box]]
Loader = Callable[[Path], tuple[np.ndarray, int]]


def region(frame: np.ndarray, box: Box) -> np.ndarray:
    """The ground-truth photo region of a synthetic frame (a copy)."""
    return frame[box.y : box.y + box.h, box.x : box.x + box.w].copy()


def cropped_back(dpi: int, **kwargs) -> np.ndarray:
    """A perfectly cropped synthetic back."""
    frame, box = make_frame(dpi=dpi, side="back", **kwargs)
    return region(frame, box)


def batch(
    sheets: Sequence[Sheet], front_first: Sequence[bool], dpi: int
) -> tuple[list[Path], Loader]:
    """Pages ``page-001.png`` ... in scan order plus a loader serving them from memory.

    ``front_first[i]`` says whether sheet ``i`` is scanned front page first or back page first.
    """
    pages: list[Path] = []
    frames: dict[Path, tuple[np.ndarray, int]] = {}
    for number, ((front, _), (back, _)) in enumerate(sheets):
        first, second = (front, back) if front_first[number] else (back, front)
        for offset, frame in enumerate((first, second)):
            path = Path(f"page-{2 * number + offset + 1:03d}.png")
            pages.append(path)
            frames[path] = (frame, dpi)
    return pages, lambda path: frames[path]


def page_number(path: Path) -> int:
    return int(path.stem.split("-")[1])
