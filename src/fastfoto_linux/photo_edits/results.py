"""Result records of preview and save, kept apart from the recipe contract."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastfoto_linux.photo_edits.model import PhotoEditRecipe


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
    working: Path | None = field(default=None, kw_only=True)
    straightened: Path | None = field(default=None, kw_only=True)


@dataclass(frozen=True)
class SavedPhotoEdit:
    """An immutable derivative and its committed recipe sidecar."""

    image: Path
    sidecar: Path
    recipe: "PhotoEditRecipe"
