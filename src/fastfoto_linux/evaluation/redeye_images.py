"""A safe image loader: contained paths, byte and pixel caps, no surprises."""

from pathlib import Path

import numpy as np

MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_PIXELS = 89_000_000


class ImageError(Exception):
    """An image that cannot be evaluated; ``code`` is the reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def read_contained(root: Path, rel: str) -> bytes:
    """The bytes of the regular file ``rel`` under ``root`` (symlinks are followed, then contained)."""
    raise NotImplementedError


def decode_image(data: bytes) -> np.ndarray:
    """Decode to RGB uint8, checking the header size before the pixels are loaded."""
    raise NotImplementedError


def load_image(root: Path, rel: str, sha256: str) -> np.ndarray:
    raise NotImplementedError
