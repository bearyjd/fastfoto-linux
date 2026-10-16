from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QUrl
from PySide6.QtTest import QSignalSpy

from fastfoto_linux.gui.photos import PhotoItem, item_from_files
from fastfoto_linux.gui.qt.photos_model import PhotosModel
from tests.gui.helpers import written

DIRECTORY = Path("/srv/demo/FastFoto/Family Trips")


def item(index: int, **overrides: Any) -> PhotoItem:
    base = item_from_files(written(DIRECTORY, index, back=True))
    return PhotoItem(**{**base.__dict__, **overrides})


def url(path: Path) -> str:
    return bytes(QUrl.fromLocalFile(str(path)).toEncoded()).decode()


@pytest.fixture
def model(qapp: Any) -> PhotosModel:
    return PhotosModel()


def role(model: PhotosModel, name: str) -> int:
    return next(key for key, value in model.roleNames().items() if bytes(value).decode() == name)


def test_a_new_model_is_empty(model: PhotosModel) -> None:
    assert model.rowCount() == 0


def test_the_roles_are_named_for_qml(model: PhotosModel) -> None:
    names = {bytes(value).decode() for value in model.roleNames().values()}
    assert names == {
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
    }


def test_a_row_serves_file_urls_and_flags(model: PhotosModel) -> None:
    model.set_items((item(7),))
    row = model.index(0, 0)
    assert model.data(row, role(model, "frontUrl")) == url(DIRECTORY / "Family Trips_0007.jpg")
    assert model.data(row, role(model, "enhancedUrl")) == url(DIRECTORY / "Family Trips_0007_a.jpg")
    assert model.data(row, role(model, "backUrl")) == url(DIRECTORY / "Family Trips_0007_b.jpg")
    assert model.data(row, role(model, "hasEnhanced")) is True
    assert model.data(row, role(model, "hasBack")) is True
    assert model.data(row, role(model, "album")) == "Family Trips"
    assert model.data(row, role(model, "number")) == 7
    assert model.data(row, role(model, "title")) == "Family Trips_0007"


def test_missing_files_are_empty_urls_and_false_flags(model: PhotosModel) -> None:
    model.set_items((item(1, enhanced=None, back=None),))
    row = model.index(0, 0)
    assert model.data(row, role(model, "enhancedUrl")) == ""
    assert model.data(row, role(model, "backUrl")) == ""
    assert model.data(row, role(model, "hasEnhanced")) is False
    assert model.data(row, role(model, "hasBack")) is False


def test_a_normal_photo_is_not_flagged_as_unprocessed(model: PhotosModel) -> None:
    model.set_items((item(1),))
    row = model.index(0, 0)
    assert model.data(row, role(model, "unprocessed")) is False
    assert model.data(row, role(model, "reason")) == ""


def test_a_whole_page_is_flagged_with_its_reason(model: PhotosModel) -> None:
    model.set_items((item(2, unprocessed_reason="the photo's edges were not found"),))
    row = model.index(0, 0)
    assert model.data(row, role(model, "unprocessed")) is True
    assert model.data(row, role(model, "reason")) == "the photo's edges were not found"


def test_a_longer_list_adds_rows_without_resetting(model: PhotosModel) -> None:
    inserted = QSignalSpy(model.rowsInserted)
    reset = QSignalSpy(model.modelReset)
    model.set_items((item(1),))
    model.set_items((item(1), item(2), item(3)))
    assert model.rowCount() == 3
    assert [(inserted.at(n)[1], inserted.at(n)[2]) for n in range(inserted.count())] == [
        (0, 0),
        (1, 2),
    ]
    assert reset.count() == 0


def test_the_same_list_changes_nothing(model: PhotosModel) -> None:
    model.set_items((item(1),))
    inserted = QSignalSpy(model.rowsInserted)
    reset = QSignalSpy(model.modelReset)
    model.set_items((item(1),))
    assert inserted.count() == 0
    assert reset.count() == 0


def test_a_different_list_resets_the_model(model: PhotosModel) -> None:
    model.set_items((item(1), item(2)))
    reset = QSignalSpy(model.modelReset)
    model.set_items((item(9),))
    assert reset.count() == 1
    assert model.rowCount() == 1
    model.set_items(())
    assert model.rowCount() == 0


def test_a_row_outside_the_model_has_no_data(model: PhotosModel) -> None:
    model.set_items((item(1),))
    assert model.data(model.index(5, 0), role(model, "title")) is None


def test_a_photo_is_titled_by_its_file_name_not_its_folder(model: PhotosModel) -> None:
    model.set_items((item(3),))
    assert model.data(model.index(0, 0), role(model, "title")) == "Family Trips_0003"
