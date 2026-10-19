"""Red-eye suggestions, manual ellipses and source-based RGB rendering."""

from pathlib import Path
from threading import Event

import numpy as np

from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.photo_edits.model import (
    EyeEdit,
    PhotoEditRecipe,
    PhotoPreview,
    PhotoSource,
)


def detect_eyes(
    source: PhotoSource, *, cancel: Event, detector: FaceDetector | None = None
) -> tuple[EyeEdit, ...]:
    """Return pending suggestions using the existing full-resolution detection gates."""
    raise NotImplementedError("photo eye suggestions are pending")


def manual_eye(  # noqa: PLR0913 - the explicit source-space ellipse is the public contract
    source: PhotoSource,
    *,
    eye_id: str,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    strength: int = 100,
) -> EyeEdit:
    """An accepted manual pupil mask, clipped to the retained original."""
    raise NotImplementedError("manual eye ellipses are pending")


def render(source: PhotoSource, recipe: PhotoEditRecipe, *, cancel: Event) -> np.ndarray:
    """Render accepted corrections from source without changing its pixels."""
    raise NotImplementedError("photo edit rendering is pending")


def make_preview(  # noqa: PLR0913 - preview geometry and cancellation are explicit
    source: PhotoSource,
    recipe: PhotoEditRecipe,
    *,
    cache_dir: Path,
    generation: int,
    cancel: Event,
    selected_id: str | None = None,
) -> PhotoPreview:
    """Publish private bounded previews, with an optional full-resolution eye crop."""
    raise NotImplementedError("photo edit previews are pending")
