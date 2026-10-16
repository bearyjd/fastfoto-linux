"""Black-and-white conversion with an adaptive threshold."""

import numpy as np


def binarise(grey: np.ndarray, dpi: int) -> np.ndarray:
    """A boolean array, True where the page is white, from an ``HxW`` uint8 grey page.

    The threshold follows the local paper tone over a window of a few millimetres at ``dpi``,
    so uneven lighting does not turn paper black. The input is not modified.
    """
    raise NotImplementedError
