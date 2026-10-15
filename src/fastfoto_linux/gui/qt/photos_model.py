"""The results grid's model: one row per written photo, with the file URLs QML shows."""

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, QPersistentModelIndex, Qt

from fastfoto_linux.gui.photos import PhotoItem


class PhotosModel(QAbstractListModel):
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        raise NotImplementedError

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        raise NotImplementedError

    def roleNames(self) -> dict[int, QByteArray]:
        raise NotImplementedError

    def set_items(self, items: tuple[PhotoItem, ...]) -> None:
        raise NotImplementedError
