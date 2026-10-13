"""Load raw scanimage PNG frames together with their resolution."""

from pathlib import Path

import numpy as np


def load_frame(path: str | Path, dpi: int | None = None) -> tuple[np.ndarray, int]:
    """Read an RGB frame and return ``(array, dpi)``."""
    raise NotImplementedError
