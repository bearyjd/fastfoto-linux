"""What QML reads about Documents mode: the form, searchable text, and the list of PDFs.

Held by the bridge as ``bridge.documents``; the bridge calls ``refresh`` whenever the page changes.
"""

from dataclasses import asdict
from typing import Any

from PySide6.QtCore import Property, QObject, Signal

from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.docform import DOCUMENT_COLOURS
from fastfoto_linux.gui.qt.documents_model import DocumentsModel
from fastfoto_linux.session import DOCUMENT_DPI

HEADING = "Documents"


class DocumentsView(QObject):
    changed = Signal()

    def __init__(self, controller: Controller, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._items = DocumentsModel(self)

    def refresh(self) -> None:
        """The page changed: show the PDFs it has now and tell QML to read everything again."""
        self._items.set_items(self._controller.documents)
        self.changed.emit()

    @Property("QVariantMap", notify=changed)
    def form(self) -> dict[str, Any]:
        return asdict(self._controller.document_form)

    @Property(bool, notify=changed)
    def ocrAvailable(self) -> bool:
        return self._controller.ocr_available

    @Property(str, notify=changed)
    def ocrHint(self) -> str:
        return self._controller.ocr_hint

    @Property(bool, notify=changed)
    def searchableChecked(self) -> bool:
        return self._controller.searchable_checked

    @Property(int, notify=changed)
    def count(self) -> int:
        return len(self._controller.documents)

    @Property(str, notify=changed)
    def heading(self) -> str:
        count = len(self._controller.documents)
        return f"{HEADING} ({count})" if count else HEADING

    @Property(QObject, constant=True)
    def items(self) -> DocumentsModel:
        return self._items

    @Property("QVariantList", constant=True)
    def dpiChoices(self) -> list[int]:
        return list(DOCUMENT_DPI)

    @Property("QVariantList", constant=True)
    def colourChoices(self) -> list[str]:
        return list(DOCUMENT_COLOURS)
