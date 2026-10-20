"""Crop-and-rotate mode and geometry actions for the Qt-free photo editor."""

from dataclasses import replace
from typing import TYPE_CHECKING

from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.photo_edits import PhotoEditRecipe, PhotoGeometry, update_geometry

if TYPE_CHECKING:
    from fastfoto_linux.gui.photoeditside import PhotoEditSide

EYES_BLOCKED = "Leave Crop and rotate to edit eyes."
GEOMETRY_BLOCKED = "Turn on Crop and rotate to change the framing."


class PhotoGeometryActions:
    """Mixin for ``PhotoEditSide``: the mode lives here, never in the page."""

    geometry_mode = False

    @property
    def can_edit_eyes(self: "PhotoEditSide") -> bool:
        return self.can_edit and not self.geometry_mode

    def _require_eye_edit(self: "PhotoEditSide") -> None:
        if self.geometry_mode:
            raise ActionBlockedError(EYES_BLOCKED)

    def _require_geometry_edit(self: "PhotoEditSide") -> PhotoEditRecipe:
        recipe = self._require_edit()
        if not self.geometry_mode:
            raise ActionBlockedError(GEOMETRY_BLOCKED)
        return recipe

    def set_geometry_mode(self: "PhotoEditSide", value: bool) -> None:
        self._require_edit()
        self.geometry_mode = bool(value)
        self._changed()

    def _set_geometry(self: "PhotoEditSide", geometry: PhotoGeometry) -> None:
        recipe = self._require_geometry_edit()
        updated = update_geometry(recipe, geometry)
        if updated is not recipe:
            self._change(updated)

    def rotate(self: "PhotoEditSide", clockwise: bool) -> None:
        recipe = self._require_geometry_edit()
        turns = (recipe.geometry.quarter_turns + (1 if clockwise else 3)) % 4
        self._set_geometry(replace(recipe.geometry, quarter_turns=turns))

    def set_crop(self: "PhotoEditSide", left: int, top: int, right: int, bottom: int) -> None:
        recipe = self._require_geometry_edit()
        self._set_geometry(replace(recipe.geometry, crop=(left, top, right, bottom)))

    def clear_crop(self: "PhotoEditSide") -> None:
        recipe = self._require_geometry_edit()
        self._set_geometry(replace(recipe.geometry, crop=None))

    def reset_geometry(self: "PhotoEditSide") -> None:
        self._require_geometry_edit()
        self._set_geometry(PhotoGeometry())
