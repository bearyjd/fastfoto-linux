"""Review row edits and moves preserve grid indexes without resetting the model."""

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy

from fastfoto_linux.gui.qt.review_model import ReviewModel
from fastfoto_linux.gui.review import ReviewState, review_items
from tests.gui.review_helpers import draft


def test_review_roles_and_invalid_indexes(qapp, tmp_path):
    model = ReviewModel()
    model.set_items(review_items(ReviewState(draft(tmp_path))))
    assert model.rowCount() == 3
    assert {bytes(name).decode() for name in model.roleNames().values()} >= {
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
    }
    assert model.get(1)["dropped"]
    assert model.get(-1) == {}
    assert model.data(model.index(100, 0), Qt.ItemDataRole.DisplayRole) is None


def test_edits_emit_row_changes_and_reorders_emit_moves(qapp, tmp_path):
    model = ReviewModel()
    state = ReviewState(draft(tmp_path))
    model.set_items(review_items(state))
    reset, changed, moved = (
        QSignalSpy(model.modelReset),
        QSignalSpy(model.dataChanged),
        QSignalSpy(model.rowsMoved),
    )
    state = state.rotate(3, 1)
    model.set_items(review_items(state))
    assert changed.count() == 1
    assert reset.count() == 0
    model.set_items(review_items(state.move(3, 0)))
    assert moved.count() >= 1
    assert reset.count() == 0
    assert model.get(0)["number"] == 3


def test_filter_uses_row_removals_and_insertions(qapp, tmp_path):
    model = ReviewModel()
    state = ReviewState(draft(tmp_path))
    model.set_items(review_items(state))
    reset = QSignalSpy(model.modelReset)
    model.set_items(review_items(state.only_flagged(True)))
    assert model.rowCount() == 1
    model.set_items(review_items(state))
    assert model.rowCount() == 3
    assert reset.count() == 0
