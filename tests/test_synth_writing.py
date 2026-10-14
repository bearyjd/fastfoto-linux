import cv2
import numpy as np

from tests.sides_helpers import cropped_back
from tests.synth import DARK_IMPRINT_GREY, WRITING_GREY, make_frame

DPI = 150


def _grey(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)


def _blobs(grey: np.ndarray, below: int) -> int:
    count, *_ = cv2.connectedComponentsWithStats((grey < below).astype(np.uint8), connectivity=8)
    return count - 1


def test_note_is_two_dark_connected_words_on_a_back() -> None:
    back = cropped_back(DPI, note=True, imprint=False)
    grey = _grey(back)
    assert _blobs(grey, 150) == 2
    assert grey.min() <= WRITING_GREY + 2
    plain = cropped_back(DPI, imprint=False)
    assert 0 < (grey < 150).sum() < 0.01 * grey.size
    assert (_grey(plain) >= 150).all()


def test_note_is_deterministic_and_ignored_on_fronts() -> None:
    first, _ = make_frame(dpi=DPI, side="back", note=True, rng_seed=4)
    again, _ = make_frame(dpi=DPI, side="back", note=True, rng_seed=4)
    assert np.array_equal(first, again)
    front_off, _ = make_frame(dpi=DPI, side="front")
    front_on, _ = make_frame(dpi=DPI, side="front", note=True, dark_imprint=True)
    assert np.array_equal(front_off, front_on)


def test_dark_imprint_is_ink_dark_but_never_as_dark_as_pen() -> None:
    back = cropped_back(DPI, dark_imprint=True, imprint=False)
    grey = _grey(back)
    dark = grey[grey < 200]
    assert dark.size > 0
    assert dark.min() == DARK_IMPRINT_GREY  # darker than ink threshold, lighter than pen
    assert _blobs(grey, 170) >= 10  # a line of characters plus the bars
    assert _blobs(_grey(cropped_back(DPI, imprint=True)), 170) == 0  # the faint one stays faint
