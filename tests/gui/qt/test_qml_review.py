"""The review screen against its public backend contract, without scans or OCR."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest

from tests.gui.qt.qt_helpers import child, click, invoke, settle

pytestmark = pytest.mark.usefixtures("kirigami")
QML = Path(__file__).resolve().parents[3] / "src/fastfoto_linux/gui/qml"


class Pages(QAbstractListModel):
    roles = (
        "orderIndex",
        "number",
        "thumbUrl",
        "included",
        "turns",
        "flags",
        "flagText",
        "marks",
        "startsPart",
        "part",
        "dropped",
    )

    def __init__(self):
        super().__init__()
        self.rows = [
            dict(
                orderIndex=n - 1,
                number=n,
                thumbUrl="",
                included=n != 2,
                turns=0,
                flags=["few_marks"] if n == 2 else [],
                flagText="Few marks",
                marks=[],
                startsPart=n == 3,
                part=2 if n > 2 else 1,
                dropped=n == 2,
            )
            for n in range(1, 5)
        ]

    def roleNames(self):
        return {Qt.ItemDataRole.UserRole + i: role.encode() for i, role in enumerate(self.roles)}

    def rowCount(self, parent=QModelIndex()):  # noqa: B008 - Qt model signature
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role):
        if index.isValid() and role in self.roleNames():
            return self.rows[index.row()][self.roleNames()[role].decode()]
        return None

    @Slot(int, result="QVariantMap")
    def get(self, row):
        return self.rows[row] if 0 <= row < len(self.rows) else {}


class Review(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.model = Pages()
        self.calls = []
        self.filtered = False

    active = Property(bool, lambda self: True, notify=changed)
    items = Property(QObject, lambda self: self.model, constant=True)
    summary = Property(str, lambda self: "4 pages → 2 PDFs", notify=changed)
    canSave = Property(bool, lambda self: True, notify=changed)
    flaggedCount = Property(int, lambda self: 1, notify=changed)
    flaggedOnly = Property(bool, lambda self: self.filtered, notify=changed)
    focusNumber = Property(int, lambda self: 1, notify=changed)
    parts = Property(
        "QVariantList",
        lambda self: [
            {"number": 1, "name": "Letters", "pages": 2},
            {"number": 2, "name": "Receipts", "pages": 1},
        ],
        notify=changed,
    )
    previewUrl = Property(str, lambda self: "", notify=changed)
    previewNumber = Property(int, lambda self: 1, notify=changed)

    @Slot(int)
    def toggle(self, number):
        self.calls.append(("toggle", number))

    @Slot(int, int)
    def rotate(self, number, turns):
        self.calls.append(("rotate", number, turns))

    @Slot(int, int)
    def move(self, number, to):
        self.calls.append(("move", number, to))

    @Slot(int)
    def toggleSplit(self, number):
        self.calls.append(("split", number))

    @Slot(int)
    def focus(self, number):
        self.calls.append(("focus", number))

    @Slot(bool)
    def setFlaggedOnly(self, value):
        self.filtered = value
        self.changed.emit()

    @Slot(int, str)
    def setPartName(self, number, name):
        self.calls.append(("name", number, name))

    @Slot(int, result=str)
    def preview(self, number):
        self.calls.append(("preview", number))
        return ""

    @Slot()
    def save(self):
        self.calls.append(("save",))

    @Slot()
    def back(self):
        self.calls.append(("back",))


class Backend(QObject):
    def __init__(self, review):
        super().__init__()
        self.review_object = review

    review = Property(QObject, lambda self: self.review_object, constant=True)
    bannerKind = Property(str, lambda self: "", constant=True)
    bannerHtml = Property(str, lambda self: "", constant=True)
    busy = Property(bool, lambda self: False, constant=True)


@pytest.fixture
def screen(messages: list[str]) -> Iterator[tuple[Any, Review, list[str]]]:
    review = Review()
    backend = Backend(review)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(v.toString() for v in values))
    engine.rootContext().setContextProperty("bridge", backend)
    harness = """import QtQuick
import org.kde.kirigami as Kirigami
import "."
Kirigami.ApplicationWindow { visible: true; width: 1000; height: 750
    pageStack.initialPage: ReviewPage {}
}"""
    engine.loadData(harness.encode(), QUrl.fromLocalFile(str(QML / "ReviewHarness.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    settle()
    yield window, review, warnings
    window.close()
    window.deleteLater()
    engine.deleteLater()
    settle()
    assert messages == []


def test_review_grid_summary_parts_and_buttons(screen):
    window, review, warnings = screen
    assert child(window, "reviewGrid").property("count") == 4
    assert child(window, "reviewSummary").property("text") == "4 pages → 2 PDFs"
    assert child(window, "reviewPartNames").property("count") == 2
    click(child(window, "reviewSaveButton"))
    click(child(window, "reviewBackButton"))
    assert [c for c in review.calls if c[0] != "focus"] == [("save",), ("back",)]
    assert warnings == []


def test_review_keyboard_edits_and_preview(screen):
    window, review, warnings = screen
    grid = child(window, "reviewGrid")
    invoke(grid, "forceActiveFocus")
    for key, modifier in [
        (Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_R, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_R, Qt.KeyboardModifier.ShiftModifier),
        (Qt.Key.Key_S, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier),
        (Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
    ]:
        QTest.keyClick(window, key, modifier)
    assert ("toggle", 1) in review.calls
    assert ("rotate", 1, 1) in review.calls
    assert ("rotate", 1, -1) in review.calls
    assert ("split", 1) in review.calls
    assert ("move", 1, 1) in review.calls
    assert ("preview", 1) in review.calls
    assert warnings == []


def test_review_flagged_filter(screen):
    window, review, warnings = screen
    click(child(window, "reviewFlaggedOnly"))
    assert review.filtered
    assert warnings == []
