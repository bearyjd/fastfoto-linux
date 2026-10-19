"""Photo review controls load in the real window and map zoomed image pointers."""

from pathlib import Path

import pytest

from tests.gui.qt import require_qt

require_qt()

from PIL import Image
from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QSignalSpy, QTest

from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, invoke, settle, wait_until
from tests.gui.qt.test_photo_edit_view import open_editor

open_window = test_qml.open_window

pytestmark = pytest.mark.usefixtures("kirigami")
QML = Path(__file__).resolve().parents[3] / "src/fastfoto_linux/gui/qml"


def test_review_page_exposes_decisions_numeric_adjustments_compare_and_save(
    make_bridge, open_window, out
):
    bridge, view, _worker = open_editor(make_bridge, out)
    window, warnings = open_window(bridge)
    settle()
    page = child(window, "photoEditPage")
    wait_until(
        lambda: (
            page.property("enabled")
            and page.property("opacity") >= 0.99
            and abs(page.mapToScene(QPointF(0, 0)).x()) < 1
        ),
        "photo review navigation to finish",
    )
    for name in (
        "photoAccept",
        "photoReject",
        "photoStrength",
        "photoCenterX",
        "photoCenterY",
        "photoRadiusX",
        "photoRadiusY",
        "photoUndo",
        "photoReset",
        "photoBeforeAfter",
        "photoEyeRoi",
        "photoSaveCopy",
        "photoOpenSaved",
        "photoEditBack",
    ):
        assert child(page, name) is not None
    assert child(page, "photoSaveCopy").property("enabled") == view.canSave
    assert "reduced" in child(page, "photoReducedLabel").property("text").lower()
    assert "1:1" in child(page, "photoEyeRoiLabel").property("text")
    invoke(child(page, "photoAccept"), "clicked")
    assert view.candidates[0]["accepted"]
    invoke(child(page, "photoUndo"), "clicked")
    assert not view.candidates[0]["accepted"]
    assert warnings == []


def test_actual_qml_canvas_maps_letterbox_zoom_pan_and_emits_canonical_ellipse(qapp, out, messages):
    path = QML / "PhotoEditCanvas.qml"
    assert path.exists(), "photo canvas must expose its real pointer transform for Qt smoke tests"
    image = out / "canvas-preview.png"
    Image.new("RGB", (800, 400), (100, 100, 100)).save(image)
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    assert component.isReady(), [error.toString() for error in component.errors()]
    canvas = component.createWithInitialProperties(
        dict(
            width=800.0,
            height=600.0,
            imageUrl=QUrl.fromLocalFile(str(image)).toString(),
            sourceWidth=4000,
            sourceHeight=2000,
            viewZoom=2.0,
            panX=37.0,
            panY=-19.0,
        )
    )
    assert canvas is not None
    try:
        settle()
        # sourcePoint accepts canvas coordinates and maps through the zoomed/panned Image.
        point = QMetaObject.invokeMethod(
            canvas, "sourcePoint", Q_RETURN_ARG(QPointF), Q_ARG(float, 437.0), Q_ARG(float, 281.0)
        )
        assert (point.x(), point.y()) == pytest.approx((2000, 1000))
        spy = QSignalSpy(canvas.ellipseRequested)
        assert QMetaObject.invokeMethod(
            canvas,
            "commitEllipse",
            Q_ARG(float, 237.0),
            Q_ARG(float, 181.0),
            Q_ARG(float, 637.0),
            Q_ARG(float, 381.0),
        )
        assert spy.count() == 1
        assert tuple(spy.at(0)) == pytest.approx((2000, 1000, 500, 250))
        assert messages == []
    finally:
        canvas.deleteLater()
        engine.deleteLater()
        settle()


def test_empty_suggestions_offer_manual_eye_and_dirty_back_confirmation(
    make_bridge, open_window, out
):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    settle()
    page = child(window, "photoEditPage")
    wait_until(
        lambda: (
            page.property("enabled")
            and page.property("opacity") >= 0.99
            and abs(page.mapToScene(QPointF(0, 0)).x()) < 1
        ),
        "photo review navigation to finish",
    )
    assert child(page, "photoNoSuggestions").property("visible")
    assert child(page, "photoManualEye").property("enabled")
    view.addEllipse(23, 23, 3, 3)
    assert view.candidates[0]["accepted"]
    invoke(child(page, "photoEditBack"), "clicked")
    settle()
    assert child(window, "photoDiscardDialog").property("visible")
    assert view.active
    assert warnings == []


@pytest.mark.parametrize("dpi", [300, 600])
def test_manual_click_uses_retained_dpi_and_source_pixels(make_bridge, open_window, out, dpi):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=(), dpi=dpi)
    bridge.setField("dpi", 600 if dpi == 300 else 300)
    window, warnings = open_window(bridge)
    page = child(window, "photoEditPage")
    wait_until(
        lambda: page.property("opacity") >= 0.99 and abs(page.mapToScene(QPointF(0, 0)).x()) < 1,
        "photo review viewport",
    )
    canvas = child(page, "photoEditCanvas")
    child(page, "photoManualEye").setProperty("checked", True)
    spy = QSignalSpy(canvas.ellipseRequested)
    position = canvas.mapToScene(QPointF(canvas.width() / 2, canvas.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=position)
    assert spy.count() == 1
    cx, cy, rx, ry = spy.at(0)
    assert (cx, cy) == pytest.approx((50, 30), abs=0.5)
    assert (rx, ry) == pytest.approx((0.6 * dpi / 25.4,) * 2)
    assert view.candidates[0]["accepted"]
    assert view.candidates[0]["origin"] == "manual"
    assert warnings == []
