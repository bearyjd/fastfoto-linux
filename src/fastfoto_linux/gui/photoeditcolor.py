"""White balance and preset actions for the Qt-free photo editor."""

from dataclasses import replace
from typing import TYPE_CHECKING

from fastfoto_linux.gui.photoeditpresets import matching_preset, preset
from fastfoto_linux.photo_edits import update_tone, update_white_balance

if TYPE_CHECKING:
    from fastfoto_linux.gui.photoeditside import PhotoEditSide

WB_FIELDS = frozenset({"temperature", "tint"})


class PhotoColorActions:
    """Mixin for ``PhotoEditSide``; values are validated by the recipe's own dataclasses."""

    @property
    def active_preset(self: "PhotoEditSide") -> str:
        return matching_preset(self.recipe)

    def set_white_balance(self: "PhotoEditSide", field: str, value: int) -> None:
        recipe = self._require_edit()
        if field not in WB_FIELDS:
            raise ValueError("Choose a temperature or tint adjustment.")
        updated = update_white_balance(recipe, replace(recipe.white_balance, **{field: value}))
        if updated is not recipe:
            self._change(updated)

    def apply_preset(self: "PhotoEditSide", preset_id: str) -> None:
        """Set every tone and white balance value at once, as one undo step."""
        recipe = self._require_edit()
        chosen = preset(preset_id)
        updated = update_white_balance(update_tone(recipe, chosen.tone), chosen.white_balance)
        if updated is not recipe:
            self._change(updated)
