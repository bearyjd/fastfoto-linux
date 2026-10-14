"""Image-array validation shared by the pipeline and enhance packages."""

import numpy as np

RGB_NDIM = 3
RGB_CHANNELS = 3


def ensure_rgb_uint8(img: np.ndarray) -> None:
    """Raise ``TypeError`` unless ``img`` is an array, ``ValueError`` unless H x W x 3 uint8."""
    if not isinstance(img, np.ndarray):
        raise TypeError(f"expected a numpy array, got {type(img).__name__}")
    if (
        img.ndim != RGB_NDIM
        or img.shape[2] != RGB_CHANNELS
        or img.dtype != np.uint8
        or img.size == 0
    ):
        raise ValueError(
            f"expected a non-empty RGB uint8 image (H x W x 3), got shape {img.shape} "
            f"dtype {img.dtype}"
        )
