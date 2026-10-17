"""The results list's model: one row per PDF, with the texts and URLs QML shows."""

from pathlib import Path
from typing import Any

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QSignalSpy

from fastfoto_linux.documents import OcrStatus
from fastfoto_linux.gui.documents import item_from_document
from fastfoto_linux.gui.qt.documents_model import DocumentsModel
from tests.gui.doc_helpers import document

ROLES = {
    "fileName",
    "folder",
    "fileUrl",
    "folderUrl",
    "pagesText",
    "droppedText",
    "hasDropped",
    "searchableText",
    "ocrWarning",
}


def role(model: DocumentsModel, name: str) -> int:
    names = {bytes(value).decode(): key for key, value in model.roleNames().items()}
    return names[name]


def value(model: DocumentsModel, row: int, name: str) -> Any:
    return model.data(model.index(row, 0), role(model, name))


def item(out: Path, **options: Any):
    return item_from_document(document(out, **options))


def test_the_roles_are_the_ones_the_list_reads(qapp: Any) -> None:
    model = DocumentsModel()
    assert {bytes(name).decode() for name in model.roleNames().values()} == ROLES


def test_a_row_carries_the_texts_of_its_item(qapp: Any, tmp_path: Path) -> None:
    model = DocumentsModel()
    model.set_items((item(tmp_path, pages=3, dropped=(2, 4)),))
    assert model.rowCount() == 1
    assert value(model, 0, "fileName") == "Document_0001.pdf"
    assert value(model, 0, "folder") == str(tmp_path)
    assert value(model, 0, "pagesText") == "3 pages"
    assert value(model, 0, "droppedText") == "Blank pages left out: 2, 4"
    assert value(model, 0, "hasDropped") is True
    assert value(model, 0, "searchableText") == "Searchable text: yes"
    assert value(model, 0, "ocrWarning") is False


def test_an_ocr_warning_and_no_dropped_pages_are_flagged(qapp: Any, tmp_path: Path) -> None:
    model = DocumentsModel()
    model.set_items((item(tmp_path, ocr=OcrStatus.TIMED_OUT),))
    assert value(model, 0, "ocrWarning") is True
    assert value(model, 0, "hasDropped") is False
    assert value(model, 0, "droppedText") == ""


def test_the_urls_are_percent_encoded_file_urls(qapp: Any, tmp_path: Path) -> None:
    folder = tmp_path / "My Scans #1"
    folder.mkdir()
    model = DocumentsModel()
    model.set_items((item(folder),))
    url = value(model, 0, "fileUrl")
    assert url == f"{Path(folder).as_uri()}/Document_0001.pdf"
    assert "%20" in url and "%23" in url
    assert value(model, 0, "folderUrl") == Path(folder).as_uri()


def test_a_row_out_of_range_has_no_data(qapp: Any, tmp_path: Path) -> None:
    model = DocumentsModel()
    model.set_items((item(tmp_path),))
    assert model.data(model.index(5, 0), role(model, "fileName")) is None
    assert model.data(QModelIndex(), Qt.ItemDataRole.DisplayRole) is None
    assert model.rowCount(model.index(0, 0)) == 0  # a list has no children


def test_new_items_are_appended_and_a_different_list_resets(qapp: Any, tmp_path: Path) -> None:
    model = DocumentsModel()
    first, second = item(tmp_path), item(tmp_path, pages=5)
    inserted = QSignalSpy(model.rowsInserted)
    reset = QSignalSpy(model.modelReset)
    model.set_items((first,))
    model.set_items((first, second))
    assert (inserted.count(), reset.count()) == (2, 0)
    model.set_items((second,))
    assert reset.count() == 1
    assert model.rowCount() == 1
    model.set_items((second,))  # the same list again: nothing to announce
    assert reset.count() == 1
