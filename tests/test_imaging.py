import numpy as np
import pytest

from fastfoto_linux import imaging
from fastfoto_linux.enhance import faces


def test_accepts_a_non_empty_rgb_uint8_array() -> None:
    assert imaging.ensure_rgb_uint8(np.zeros((4, 5, 3), dtype=np.uint8)) is None


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((4, 5), dtype=np.uint8),
        np.zeros((4, 5, 4), dtype=np.uint8),
        np.zeros((4, 5, 3), dtype=np.float32),
        np.zeros((0, 5, 3), dtype=np.uint8),
    ],
)
def test_rejects_arrays_that_are_not_rgb_uint8(bad: np.ndarray) -> None:
    with pytest.raises(ValueError, match="RGB"):
        imaging.ensure_rgb_uint8(bad)


def test_rejects_non_arrays_with_a_type_error() -> None:
    with pytest.raises(TypeError, match="numpy array"):
        imaging.ensure_rgb_uint8([[1, 2, 3]])  # type: ignore[arg-type]


def test_enhance_faces_still_exports_the_same_function() -> None:
    assert faces.ensure_rgb_uint8 is imaging.ensure_rgb_uint8
