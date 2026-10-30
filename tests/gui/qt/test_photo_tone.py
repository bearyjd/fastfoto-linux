"""Tone properties and real QML sliders use the existing editor and undo stack."""

from pathlib import Path

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest

from fastfoto_linux.photo_edits import PhotoTone
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, invoke, settle, wait_until
from tests.gui.qt.test_photo_edit_view import open_editor

open_window = test_qml.open_window
pytestmark = pytest.mark.usefixtures("kirigami")
NEUTRAL = dict(brightness=0, contrast=0, saturation=0, strength=100)


def test_qt_tone_map_slots_refresh_errors_and_reset_preserve_eyes(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out)
    assert view.color.metaObject().indexOfProperty("tone") >= 0
    assert view.color.tone == NEUTRAL
    assert view.color.metaObject().indexOfSlot("setTone(QString,int)") >= 0
    assert view.color.metaObject().indexOfSlot("resetTone()") >= 0
    view.setAccepted("left", True)
    view.color.setTone("brightness", 25)
    assert view.color.tone == {**NEUTRAL, "brightness": 25}
    draft = bridge.controller.photo_edit.recipe
    assert draft.tone == PhotoTone(brightness=25)
    view.color.setTone("unknown", 1)
    assert view.error and bridge.controller.photo_edit.recipe is draft
    view.color.setWhiteBalance("tint", -20)
    view.color.resetTone()
    assert view.color.tone == NEUTRAL and not view.error
    assert view.color.whiteBalance == dict(temperature=0, tint=0)
    assert view.candidates[0]["accepted"]
    view.undo()
    assert view.color.tone["brightness"] == 25
    assert "cropped" in view.sourceLabel.lower()
    assert "upright" in view.sourceLabel.lower()
    assert "new copy" in view.sourceLabel.lower()


def ready_page(window):
    page = child(window, "photoEditPage")
    wait_until(
        lambda: page.property("opacity") >= 0.99 and abs(page.mapToScene(QPointF(0, 0)).x()) < 1,
        "photo editor navigation",
    )
    return page


def test_real_page_has_edit_photo_heading_separate_eye_section_and_neutral_controls(
    make_bridge, open_window, out
):
    _bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(_bridge)
    page = ready_page(window)
    assert page.property("title") == "Edit photo"
    assert child(page, "photoRedEyeHeading").property("text") == "Red-eye correction"
    assert child(page, "photoResetTone").property("text") == "Reset adjustments"
    assert child(page, "photoToneStrengthLabel").property("text") == "Adjustment strength"
    for field, low, high in (
        ("brightness", -50, 50),
        ("contrast", -50, 50),
        ("saturation", -100, 100),
        ("strength", 0, 100),
    ):
        control = child(page, "photoTone" + field.capitalize())
        assert control.property("enabled")
        assert (control.property("from"), control.property("to")) == (low, high)
        assert control.property("stepSize") == 1
        assert control.property("value") == NEUTRAL[field]
    assert view.candidates == []
    assert warnings == []


@pytest.mark.parametrize("field", ["brightness", "contrast", "saturation", "strength"])
def test_actual_slider_drag_without_candidates_is_one_undo(make_bridge, open_window, out, field):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    window.setHeight(1800)
    page = ready_page(window)
    slider = child(page, "photoTone" + field.capitalize())
    initial = bridge.controller.photo_edit.recipe
    start = slider.mapToScene(QPointF(slider.width() * 0.4, slider.height() / 2)).toPoint()
    end = slider.mapToScene(QPointF(slider.width() * 0.8, slider.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window, end, delay=20)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    settle()
    assert view.color.tone[field] != NEUTRAL[field]
    assert view.canUndo and view.dirty
    view.undo()
    assert bridge.controller.photo_edit.recipe is initial
    assert view.color.tone == NEUTRAL and not view.canUndo
    assert warnings == []


def test_real_reset_adjustments_button_changes_draft_and_undo_keeps_eyes(
    make_bridge, open_window, out
):
    bridge, view, _worker = open_editor(make_bridge, out)
    window, warnings = open_window(bridge)
    page = ready_page(window)
    view.setAccepted("left", True)
    view.color.setTone("saturation", -100)
    view.color.setWhiteBalance("temperature", 40)
    adjusted = bridge.controller.photo_edit.recipe
    invoke(child(page, "photoResetTone"), "clicked")
    assert view.color.tone == NEUTRAL and view.candidates[0]["accepted"]
    assert view.color.whiteBalance == dict(temperature=0, tint=0)
    view.undo()
    assert bridge.controller.photo_edit.recipe is adjusted
    assert warnings == []


def test_real_photo_entry_reads_edit_photo(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out)
    assert view.close()
    engine = QQmlEngine()
    path = Path(__file__).resolve().parents[3] / "src/fastfoto_linux/gui/qml/PhotoCell.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    assert component.isReady(), [error.toString() for error in component.errors()]
    cell = component.createWithInitialProperties(
        dict(
            title="Synthetic photo",
            frontUrl="",
            enhancedUrl="",
            backUrl="",
            hasEnhanced=False,
            hasBack=False,
            unprocessed=False,
            reason="",
            backOnly=False,
            editReview=view,
            photoRow=0,
            reviewEligible=True,
            width=400.0,
            height=400.0,
        )
    )
    assert cell is not None
    try:
        entry = child(cell, "reviewRedEyesButton")
        assert entry.property("text") == "Edit photo"
        assert entry.property("enabled")
    finally:
        cell.deleteLater()
        engine.deleteLater()
        settle()


@pytest.mark.parametrize("field", ["brightness", "strength"])
def test_dragged_slider_still_follows_reset_adjustments_and_undo(
    make_bridge, open_window, out, field
):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    window.setHeight(1800)
    page = ready_page(window)
    slider = child(page, "photoTone" + field.capitalize())
    start = slider.mapToScene(QPointF(slider.width() * 0.4, slider.height() / 2)).toPoint()
    end = slider.mapToScene(QPointF(slider.width() * 0.8, slider.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window, end, delay=20)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    settle()
    dragged = view.color.tone[field]
    assert dragged != NEUTRAL[field] and slider.property("value") == dragged
    invoke(child(page, "photoResetTone"), "clicked")
    settle()
    assert slider.property("value") == NEUTRAL[field]
    view.undo()
    settle()
    assert slider.property("value") == dragged
    view.undo()
    settle()
    assert slider.property("value") == NEUTRAL[field]
    assert warnings == []
