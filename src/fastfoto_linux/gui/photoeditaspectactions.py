"""Crop shape actions for the Qt-free photo editor.

The shape is a UI constraint only: the recipe stores the pixel box. The lock is live while the
draft's geometry is exactly the one the last shape action produced or accepted; any other change
of geometry makes it Free again without any further code.
"""

from dataclasses import replace
from typing import TYPE_CHECKING

from fastfoto_linux.gui.photoeditaspect import (
    Box,
    Ratio,
    crop_ratio,
    default_portrait,
    fit_centred,
    swap_box,
)
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.photo_edits import (
    PhotoEditRecipe,
    PhotoGeometry,
    frame_size,
    min_crop_size,
    update_geometry,
)

if TYPE_CHECKING:
    from fastfoto_linux.gui.photoeditside import PhotoEditSide

ASPECT_TOO_SMALL = "This photo is too small for that crop shape at the 5 mm minimum."
NOT_SWAPPABLE = "Choose a crop shape that is not square to swap its orientation."


class PhotoAspectActions:
    """Mixin for ``PhotoEditSide``: the crop shape lock lives here, never in the page."""

    _aspect_preset = "free"
    _aspect_portrait = False
    _aspect_geometry: PhotoGeometry | None = None

    def _reset_aspect(self) -> None:
        self._aspect_preset, self._aspect_portrait, self._aspect_geometry = "free", False, None

    @property
    def _aspect_live(self: "PhotoEditSide") -> bool:
        return self.recipe is not None and self.recipe.geometry == self._aspect_geometry

    @property
    def crop_aspect(self: "PhotoEditSide") -> str:
        return self._aspect_preset if self._aspect_live else "free"

    @property
    def aspect_portrait(self: "PhotoEditSide") -> bool:
        return self._aspect_portrait if self._aspect_live else False

    @property
    def crop_ratio(self: "PhotoEditSide") -> Ratio | None:
        """The live shape as a ratio in the unturned frame, or None when free."""
        if self.recipe is None:
            return None
        return self._ratio(self.recipe.geometry, self.crop_aspect, self.aspect_portrait)

    @property
    def can_swap_aspect(self: "PhotoEditSide") -> bool:
        ratio = self.crop_ratio
        return ratio is not None and ratio[0] != ratio[1]

    def _ratio(
        self: "PhotoEditSide", geometry: PhotoGeometry, preset: str, portrait: bool
    ) -> Ratio | None:
        assert self.recipe is not None
        frame = frame_size(self.recipe.source, geometry)
        return crop_ratio(preset, portrait, frame=frame, quarter_turns=geometry.quarter_turns)

    def _box_and_limits(
        self: "PhotoEditSide", recipe: PhotoEditRecipe
    ) -> tuple[Box, tuple[int, int], tuple[int, int]]:
        geometry = recipe.geometry
        frame = frame_size(recipe.source, geometry)
        box = geometry.crop or (0, 0, *frame)
        return box, frame, min_crop_size(recipe.source, geometry)

    def _renotify(self: "PhotoEditSide") -> None:
        """Tell the page; a refusal or failure shown is stale now, so drop it and preview again.

        A preview of this very recipe that is still waiting or rendering stays valid, as the
        refusal did not bump the generation; asking again would discard it.
        """
        if self.error:
            self.error = ""
            if self._preview_is_coming():
                self._changed()
            else:
                self.request_preview()
        else:
            self._changed()

    def _preview_is_coming(self: "PhotoEditSide") -> bool:
        """Whether the latest request is a preview of the current recipe, not yet shown."""
        latest = self._pending or self._inflight
        return (
            latest is not None
            and latest.operation == "preview"
            and latest.recipe is self.recipe
            and latest.generation == self.generation
        )

    def _apply_aspect(
        self: "PhotoEditSide",
        recipe: PhotoEditRecipe,
        geometry: PhotoGeometry,
        preset: str,
        portrait: bool,
    ) -> None:
        updated = update_geometry(recipe, geometry)
        # The normalized geometry (a full frame is None), set before _change notifies the page.
        self._aspect_preset, self._aspect_portrait = preset, portrait
        self._aspect_geometry = updated.geometry
        if updated is recipe:
            self._renotify()
        else:
            self._change(updated)

    def set_crop_aspect(self: "PhotoEditSide", preset_id: str) -> None:
        recipe = self._require_geometry_edit()
        box, frame, minimum = self._box_and_limits(recipe)
        turns = recipe.geometry.quarter_turns
        portrait = default_portrait(box, turns)
        ratio = crop_ratio(preset_id, portrait, frame=frame, quarter_turns=turns)
        if ratio is None:
            self._aspect_preset = "free"
            self._renotify()
            return
        fitted = fit_centred(box, ratio, frame=frame, minimum=minimum)
        if fitted is None:
            raise ActionBlockedError(ASPECT_TOO_SMALL)
        geometry = replace(recipe.geometry, crop=fitted)
        self._apply_aspect(recipe, geometry, preset_id, portrait)

    def swap_crop_aspect(self: "PhotoEditSide") -> None:
        recipe = self._require_geometry_edit()
        if not self.can_swap_aspect:
            raise ActionBlockedError(NOT_SWAPPABLE)
        box, frame, minimum = self._box_and_limits(recipe)
        portrait = not self.aspect_portrait
        ratio = self._ratio(recipe.geometry, self.crop_aspect, portrait)
        assert ratio is not None
        swapped = swap_box(box, ratio, frame=frame, minimum=minimum)
        if swapped is None:
            raise ActionBlockedError(ASPECT_TOO_SMALL)
        geometry = replace(recipe.geometry, crop=swapped)
        self._apply_aspect(recipe, geometry, self.crop_aspect, portrait)

    def set_aspect_crop(
        self: "PhotoEditSide", left: int, top: int, right: int, bottom: int
    ) -> None:
        recipe = self._require_geometry_edit()
        ratio = self.crop_ratio
        if ratio is None:
            self.set_crop(left, top, right, bottom)
            return
        _box, frame, minimum = self._box_and_limits(recipe)
        fitted = fit_centred((left, top, right, bottom), ratio, frame=frame, minimum=minimum)
        if fitted is None:
            raise ActionBlockedError(ASPECT_TOO_SMALL)
        geometry = replace(recipe.geometry, crop=fitted)
        self._apply_aspect(recipe, geometry, self.crop_aspect, self.aspect_portrait)

    def _carry_aspect(self: "PhotoEditSide", before: PhotoGeometry, turns: int) -> None:
        """Called by rotate before it changes the geometry: flip the orientation, keep the lock."""
        if before == self._aspect_geometry:
            self._aspect_portrait = not self._aspect_portrait
            self._aspect_geometry = replace(before, quarter_turns=turns)
        else:
            self._aspect_preset = "free"
