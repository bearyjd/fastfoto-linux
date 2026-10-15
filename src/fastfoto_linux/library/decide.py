"""Decide, for each JPEG, whether its stored orientation needs a further quarter turn."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.library.plan import PlanRow

REASON_BACK = "back"
REASON_BACK_LOOKS_LIKE_FRONT = "back-looks-like-front"
REASON_UPRIGHT = "upright"
REASON_UNDECIDED = "undecided"
REASON_UNREADABLE = "unreadable"
REASON_MIRRORED = "mirrored-tag"
REASON_INVALID_TAG = "invalid-tag"
REASON_ROTATE = "faces-upright-after-turn"
BACK_SUFFIX = "_b"
DEFAULT_JOBS = 4


def decide_file(src: Path, relative: str, detector: FaceDetector | None = None) -> PlanRow:
    """The plan row for ``src / relative``. Never raises for a bad file: it becomes a skip row."""
    raise NotImplementedError


def decide_files(src: Path, relatives: Sequence[str], jobs: int) -> tuple[PlanRow, ...]:
    """``decide_file`` for every path, rows in the order given; ``jobs`` > 1 uses processes."""
    raise NotImplementedError


def load_working_image(data: bytes, tag: int | None) -> np.ndarray:
    """The photo as displayed (``tag`` applied), RGB uint8, decoded at about the detector size."""
    raise NotImplementedError
