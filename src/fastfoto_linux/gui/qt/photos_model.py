"""The results grid's model: one row per written photo, with the file URLs QML shows.

A sheet saved whole (not processed) is a row too, flagged ``unprocessed`` with its ``reason``.
"""

from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QUrl,
)

from fastfoto_linux.gui.photos import PhotoItem

Index = QModelIndex | QPersistentModelIndex
_FIRST_ROLE = Qt.ItemDataRole.UserRole + 1
_ROLES = (
    "title",
    "album",
    "number",
    "frontUrl",
    "enhancedUrl",
    "backUrl",
    "hasEnhanced",
    "hasBack",
    "unprocessed",
    "reason",
)


def file_url(path: Path | None) -> str:
    """The percent-encoded ``file:`` URL of a path, empty for none or for a relative one."""
    if path is None or not path.is_absolute():
        return ""
    return bytes(QUrl.fromLocalFile(str(path)).toEncoded()).decode()


def _values(item: PhotoItem) -> dict[str, object]:
    return {
        "title": item.title,
        "album": item.album,
        "number": item.index,
        "frontUrl": file_url(item.front),
        "enhancedUrl": file_url(item.enhanced),
        "backUrl": file_url(item.back),
        "hasEnhanced": item.enhanced is not None,
        "hasBack": item.back is not None,
        "unprocessed": item.unprocessed,
        "reason": item.unprocessed_reason or "",
    }


class PhotosModel(QAbstractListModel):
    """The photos written so far, in order; it only ever grows until a new scan resets it."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self._items: tuple[PhotoItem, ...] = ()

    def rowCount(self, parent: Index | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._items)

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        row = index.row()
        if not index.isValid() or not 0 <= row < len(self._items):
            return None
        name = _ROLES[role - _FIRST_ROLE] if _FIRST_ROLE <= role < _FIRST_ROLE + len(_ROLES) else ""
        return _values(self._items[row]).get(name)

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            _FIRST_ROLE + number: QByteArray(name.encode()) for number, name in enumerate(_ROLES)
        }

    def set_items(self, items: tuple[PhotoItem, ...]) -> None:
        """Show ``items``: new rows are appended when the old ones are still the start of them."""
        old = self._items
        if items == old:
            return
        if len(items) > len(old) and items[: len(old)] == old:
            self.beginInsertRows(QModelIndex(), len(old), len(items) - 1)
            self._items = items
            self.endInsertRows()
        else:
            self.beginResetModel()
            self._items = items
            self.endResetModel()
