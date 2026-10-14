"""Image-array validation shared by the pipeline and enhance packages."""

import numpy as np

RGB_NDIM = 3
RGB_CHANNELS = 3


def ensure_rgb_uint8(img: np.ndarray) -> None:
    """Raise ``TypeError`` unless ``img`` is an array, ``ValueError`` unless H x W x 3 uint8."""
    raise NotImplementedError
