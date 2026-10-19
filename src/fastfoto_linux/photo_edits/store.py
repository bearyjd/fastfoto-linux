"""Bounded recipe decoding and save-new-only derivative publication."""

from pathlib import Path
from threading import Event

from fastfoto_linux.photo_edits.model import PhotoEditRecipe, PhotoSource, SavedPhotoEdit


def recipe_bytes(recipe: PhotoEditRecipe) -> bytes:
    """Encode source identity and exact local masks as a schema-versioned JSON recipe."""
    raise NotImplementedError("photo recipe encoding is pending")


def parse_recipe(data: bytes, source: PhotoSource) -> PhotoEditRecipe:
    """Decode a bounded recipe only when its retained source identity matches."""
    raise NotImplementedError("photo recipe decoding is pending")


def save_edit(source: PhotoSource, recipe: PhotoEditRecipe, *, cancel: Event) -> SavedPhotoEdit:
    """Write a new numbered JPEG and sidecar, with sidecar as the commit marker."""
    raise NotImplementedError("photo edit publication is pending")


def open_edit(sidecar: Path) -> tuple[PhotoSource, PhotoEditRecipe]:
    """Verify source and derivative identities, then reopen without re-detecting eyes."""
    raise NotImplementedError("saved photo reopening is pending")
