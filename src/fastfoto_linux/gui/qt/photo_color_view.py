"""The colour child of the photo editor view: tone, white balance and presets."""

from dataclasses import asdict
from math import isfinite
from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QObject, Signal, Slot

from fastfoto_linux.gui.photoeditpresets import PRESETS
from fastfoto_linux.photo_edits import PhotoDetail, PhotoTone, PhotoWhiteBalance

if TYPE_CHECKING:
    from fastfoto_linux.gui.photoeditside import PhotoEditSide
    from fastfoto_linux.gui.qt.photo_edit_view import PhotoEditView


def _whole(value: object) -> int:
    """QML numbers arrive as int or float; anything else, or a fraction, is refused unconverted."""
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        if isinstance(value, int):
            return value
        if isfinite(value) and value.is_integer():
            return int(value)
    raise ValueError("Enter a whole number for this adjustment.")


class PhotoColorView(QObject):
    changed = Signal()

    def __init__(self, parent: "PhotoEditView") -> None:
        super().__init__(parent)
        self._view = parent

    @property
    def _side(self) -> "PhotoEditSide":
        return self._view._side

    @Property("QVariantMap", notify=changed)
    def tone(self) -> dict[str, int]:
        recipe = self._side.recipe
        return asdict(recipe.tone if recipe else PhotoTone())

    @Property("QVariantMap", notify=changed)
    def whiteBalance(self) -> dict[str, int]:
        recipe = self._side.recipe
        return asdict(recipe.white_balance if recipe else PhotoWhiteBalance())

    @Property("QVariantMap", notify=changed)
    def detail(self) -> dict[str, int]:
        recipe = self._side.recipe
        return asdict(recipe.detail if recipe else PhotoDetail())

    @Property("QVariantList", constant=True)
    def presets(self) -> list[dict[str, str]]:
        return [dict(id=item.id, label=item.label) for item in PRESETS]

    @Property(str, notify=changed)
    def activePreset(self) -> str:
        return self._side.active_preset

    @Slot(str, "QVariant")
    def setTone(self, field: str, value: object) -> None:
        self._view._call(lambda: self._side.set_tone(field, _whole(value)))

    @Slot()
    def resetTone(self) -> None:
        self._view._call(self._side.reset_tone)

    @Slot(str, "QVariant")
    def setWhiteBalance(self, field: str, value: object) -> None:
        self._view._call(lambda: self._side.set_white_balance(field, _whole(value)))

    @Slot(str, "QVariant")
    def setDetail(self, field: str, value: object) -> None:
        self._view._call(lambda: self._side.set_detail(field, _whole(value)))

    @Slot(str)
    def applyPreset(self, preset_id: str) -> None:
        self._view._call(self._side.apply_preset, preset_id)
