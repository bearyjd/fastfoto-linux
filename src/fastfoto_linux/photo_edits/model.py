"""Typed contract for recoverable, source-bound red-eye edits."""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
ALGORITHM_VERSION = "redeye-v1"
MAX_RECIPE_BYTES = 2_000_000
MAX_EYES = 128
MAX_MASK_PIXELS = 1_000_000
PREVIEW_MAX_PX = 1600


class PhotoEditError(ValueError):
    """A source or recipe cannot safely be edited."""


class PhotoEditCancelledError(PhotoEditError):
    """The caller cancelled before publication."""


@dataclass(frozen=True, eq=False)
class PhotoSource:
    """One retained original, decoded into canonical upright RGB pixel coordinates."""

    path: Path
    sha256: str
    byte_size: int
    width: int
    height: int
    dpi_x: float
    dpi_y: float
    effective_dpi: float
    pixels: np.ndarray = field(repr=False)
    orientation: int = 1
    exif: bytes = field(default=b"", repr=False)
    xmp: bytes = field(default=b"", repr=False)
    icc_profile: bytes | None = field(default=None, repr=False)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, eq=False)
class EyeEdit:
    """Exact full-resolution local mask and the user's decision for one pupil."""

    id: str
    origin: str
    roi: tuple[int, int, int, int]
    center: tuple[float, float]
    mask: np.ndarray = field(repr=False)
    accepted: bool = False
    strength: int = 100


@dataclass(frozen=True, eq=False)
class PhotoEditRecipe:
    """Replay from source, never from a previously encoded derivative."""

    source: PhotoSource
    eyes: tuple[EyeEdit, ...] = ()
    schema_version: int = SCHEMA_VERSION
    algorithm_version: str = ALGORITHM_VERSION
    quality: int = 95


@dataclass(frozen=True)
class PhotoPreview:
    """Bounded private preview URLs and the full-resolution coordinate space."""

    before: Path
    after: Path
    source_width: int
    source_height: int
    preview_width: int
    preview_height: int
    source_sha256: str
    generation: int
    roi_before: Path | None = None
    roi_after: Path | None = None


@dataclass(frozen=True)
class SavedPhotoEdit:
    """An immutable derivative and its committed recipe sidecar."""

    image: Path
    sidecar: Path
    recipe: PhotoEditRecipe
