"""Shared fixtures-as-functions for the album output tests."""

from pathlib import Path

import numpy as np

from fastfoto_linux.output.files import LOCK_NAME

HEIGHT, WIDTH = 40, 60
DPI = 300


def rgb(
    color: tuple[int, int, int] = (200, 30, 30), *, size: tuple[int, int] = (HEIGHT, WIDTH)
) -> np.ndarray:
    """A read-only uint8 RGB array: any in-place mutation by the writer fails loudly."""
    array = np.empty((*size, 3), dtype=np.uint8)
    array[:] = color
    array.setflags(write=False)
    return array


def make_root(parent: Path, name: str = "out") -> Path:
    """An existing output root: write_photo never creates it."""
    root = parent / name
    root.mkdir()
    return root


def names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name != LOCK_NAME)
