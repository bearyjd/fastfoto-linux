"""The results list's model for Documents mode: one row per PDF made."""

from PySide6.QtCore import QAbstractListModel

from fastfoto_linux.gui.documents import DocumentItem


class DocumentsModel(QAbstractListModel):
    def set_items(self, items: tuple[DocumentItem, ...]) -> None:
        raise NotImplementedError
