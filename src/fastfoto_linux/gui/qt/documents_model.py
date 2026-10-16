"""The results list's model for Documents mode: one row per PDF made, with the texts QML shows."""

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)

from fastfoto_linux.gui.documents import DocumentItem
from fastfoto_linux.gui.qt.photos_model import file_url

Index = QModelIndex | QPersistentModelIndex
_FIRST_ROLE = Qt.ItemDataRole.UserRole + 1
_ROLES = (
    "fileName",
    "folder",
    "fileUrl",
    "folderUrl",
    "pagesText",
    "droppedText",
    "hasDropped",
    "searchableText",
    "ocrWarning",
)


def _values(item: DocumentItem) -> dict[str, object]:
    return {
        "fileName": item.file_name,
        "folder": str(item.folder),
        "fileUrl": file_url(item.pdf),
        "folderUrl": file_url(item.folder),
        "pagesText": item.pages_text,
        "droppedText": item.dropped_text,
        "hasDropped": bool(item.dropped),
        "searchableText": item.searchable_text,
        "ocrWarning": item.ocr_warning,
    }


class DocumentsModel(QAbstractListModel):
    """The PDFs made so far, in order; it only grows until a new scan resets it."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self._items: tuple[DocumentItem, ...] = ()

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

    def set_items(self, items: tuple[DocumentItem, ...]) -> None:
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
