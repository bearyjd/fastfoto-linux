"""The crop shape child of the photo editor view: thin properties and slots over the controller."""

from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QObject, Signal, Slot

if TYPE_CHECKING:
    from fastfoto_linux.gui.photoeditside import PhotoEditSide
    from fastfoto_linux.gui.qt.photo_edit_view import PhotoEditView


class PhotoAspectView(QObject):
    changed = Signal()

    def __init__(self, parent: "PhotoEditView") -> None:
        super().__init__(parent)
        self._view = parent

    @property
    def _side(self) -> "PhotoEditSide":
        return self._view._side

    @Property(str, notify=changed)
    def preset(self) -> str:
        return self._side.crop_aspect

    @Property(bool, notify=changed)
    def portrait(self) -> bool:
        return self._side.aspect_portrait

    @Property("QVariantList", notify=changed)
    def ratio(self) -> list[int]:
        return list(self._side.crop_ratio or ())

    @Property(bool, notify=changed)
    def canSwap(self) -> bool:
        return self._side.can_swap_aspect

    @Property(str, notify=changed)
    def shapeText(self) -> str:
        """The saved picture's shape, e.g. "3:4 portrait", "1:1" or "Original, landscape"."""
        side, ratio = self._side, self._side.crop_ratio
        if ratio is None or side.recipe is None:
            return ""
        orientation = "portrait" if side.aspect_portrait else "landscape"
        if side.crop_aspect == "original":
            return "Original" if ratio[0] == ratio[1] else f"Original, {orientation}"
        if ratio[0] == ratio[1]:
            return "1:1"
        rw, rh = ratio
        dw, dh = (rh, rw) if side.recipe.geometry.quarter_turns % 2 else (rw, rh)
        return f"{dw}:{dh} {orientation}"

    @Slot(str)
    def setPreset(self, preset_id: str) -> None:
        self._view._call(self._side.set_crop_aspect, preset_id)

    @Slot()
    def swap(self) -> None:
        self._view._call(self._side.swap_crop_aspect)

    @Slot(int, int, int, int)
    def setAspectCrop(self, left: int, top: int, right: int, bottom: int) -> None:
        self._view._call(self._side.set_aspect_crop, left, top, right, bottom)
