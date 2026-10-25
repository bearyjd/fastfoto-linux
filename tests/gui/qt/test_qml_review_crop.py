"""The hand crop in the real preview dialog: drag, keys, reset and the words around them."""

import pytest

from tests.gui.qt import require_qt

require_qt()

from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQml import QQmlProperty, qmlContext
from PySide6.QtTest import QTest

from fastfoto_linux.documents.draft import PageEdit
from tests.gui.qt import test_qml_documents, test_qml_review_window
from tests.gui.qt.qt_helpers import child, click, invoke, settle, wait_until

pytestmark = pytest.mark.usefixtures("kirigami")
review_window = test_qml_review_window.review_window
open_window = test_qml_documents.open_window
UNITS = 10_000


def accessible_name(item):
    return QQmlProperty(item, "Accessible.name", qmlContext(item)).read()


def crop_of(bridge, number=1):
    return bridge.controller.review.state.draft.edits.get(number, PageEdit()).crop


@pytest.fixture
def source_preview(review_window):
    """The preview dialog of page 1, its source preview delivered (a 100 x 200 px page, 300 dpi)."""
    window, bridge, worker, source, warnings = review_window
    invoke(child(window, "reviewGrid"), "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Return)
    preview = source.raw_dir / "previews" / "page-0001.jpg"
    preview.parent.mkdir(exist_ok=True)
    Image.new("RGB", (40, 80), "white").save(preview)
    bridge.controller.review.preview_ready((source, 1, preview, "", (100, 200, 300)))
    settle()
    wait_until(lambda: child(window, "reviewPreviewImage").property("paintedWidth") > 0, "image")
    return window, bridge, worker, source, warnings


def point(window, fx, fy):
    image = child(window, "reviewPreviewImage")
    left = (image.width() - image.property("paintedWidth")) / 2
    top = (image.height() - image.property("paintedHeight")) / 2
    x = left + fx * image.property("paintedWidth")
    y = top + fy * image.property("paintedHeight")
    return image.mapToScene(QPointF(x, y)).toPoint()


def drag(window, start, end):
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window, end, delay=20)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    settle()


def enter_crop_mode(window):
    click(child(window, "reviewCropButton"))
    settle()


def test_the_crop_controls_exist_with_names_and_words(source_preview):
    window, bridge, _worker, _source, warnings = source_preview
    assert child(window, "reviewCropButton").property("text") == "Crop"
    assert child(window, "reviewCropResetButton").property("text") == "Reset crop"
    assert not child(window, "reviewCropResetButton").property("enabled")
    for name in ("reviewCropButton", "reviewCropResetButton", "reviewCropOverlay"):
        assert accessible_name(child(window, name))
    assert child(window, "reviewCropHint").property("text") == (
        "Drag a rectangle on the page to keep only that area. The page is not analysed again."
    )
    assert child(window, "reviewCropTooSmall").property("text") == (
        "The crop must be at least 5 mm on each side."
    )
    assert not child(window, "reviewCropHint").property("visible")
    assert not child(window, "reviewCropTooSmall").property("visible")
    assert bridge.review.previewCropMode
    assert warnings == []


def test_the_crop_button_is_for_the_source_view_only(source_preview):
    window, bridge, _worker, _source, _warnings = source_preview
    assert child(window, "reviewCropButton").property("visible")
    bridge.review.previewMode(1, "output")
    settle()
    assert not child(window, "reviewCropButton").property("visible")
    assert not bridge.review.previewCropMode


def test_dragging_a_rectangle_crops_the_page(source_preview):
    window, bridge, _worker, _source, warnings = source_preview
    enter_crop_mode(window)
    assert child(window, "reviewCropHint").property("visible")
    drag(window, point(window, 0.2, 0.2), point(window, 0.8, 0.8))
    crop = crop_of(bridge)
    assert crop is not None
    assert abs(crop.left - 2000) < 300 and abs(crop.top - 2000) < 300
    assert abs(crop.right - 8000) < 300 and abs(crop.bottom - 8000) < 300
    assert len(bridge.review.previewCropRect) == 4
    assert child(window, "reviewCropRect").property("visible")
    assert child(window, "reviewCropResetButton").property("enabled")
    assert not child(window, "reviewCropTooSmall").property("visible")
    assert warnings == []


def test_a_drag_under_five_millimetres_says_so_and_changes_nothing(source_preview):
    window, bridge, _worker, _source, _warnings = source_preview
    enter_crop_mode(window)
    drag(window, point(window, 0.4, 0.4), point(window, 0.45, 0.45))
    assert crop_of(bridge) is None
    assert child(window, "reviewCropTooSmall").property("visible")
    drag(window, point(window, 0.2, 0.2), point(window, 0.8, 0.8))
    assert crop_of(bridge) is not None
    assert not child(window, "reviewCropTooSmall").property("visible")


def test_a_drag_outside_the_crop_mode_does_nothing(source_preview):
    window, bridge, _worker, _source, _warnings = source_preview
    drag(window, point(window, 0.2, 0.2), point(window, 0.8, 0.8))
    assert crop_of(bridge) is None


def test_reset_crop_clears_it(source_preview):
    window, bridge, _worker, _source, _warnings = source_preview
    enter_crop_mode(window)
    drag(window, point(window, 0.2, 0.2), point(window, 0.8, 0.8))
    click(child(window, "reviewCropResetButton"))
    settle()
    assert crop_of(bridge) is None
    assert list(bridge.review.previewCropRect) == []
    assert not child(window, "reviewCropResetButton").property("enabled")


def test_the_keys_move_the_rectangle_enter_applies_and_escape_cancels(source_preview):
    window, bridge, _worker, _source, _warnings = source_preview
    enter_crop_mode(window)
    overlay = child(window, "reviewCropOverlay")
    assert overlay.property("activeFocus")
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Right)
    QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Return)
    settle()
    crop = crop_of(bridge)
    assert crop is not None
    assert crop.left > 1000 + 100 and crop.top > 1000 and crop.right > crop.left
    first = crop
    enter_crop_mode(window)
    QTest.keyClick(window, Qt.Key.Key_Left)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    settle()
    assert crop_of(bridge) == first
    assert not child(window, "reviewCropHint").property("visible")
    assert child(window, "reviewPreviewDialog").property("visible")


def test_shift_arrows_resize_and_the_minimum_is_reported(source_preview):
    window, bridge, _worker, _source, _warnings = source_preview
    enter_crop_mode(window)
    for _ in range(40):
        QTest.keyClick(window, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(window, Qt.Key.Key_Return)
    settle()
    assert child(window, "reviewCropTooSmall").property("visible")
    assert crop_of(bridge) is None


def test_a_crop_marks_the_page_cell_cropped(source_preview):
    _window, bridge, _worker, _source, _warnings = source_preview
    bridge.review.setCrop(1, 1000, 1000, 9000, 9000)
    settle()
    assert bridge.review.items.get(0)["cropped"] is True
    assert bridge.review.items.get(1)["cropped"] is False


def test_a_bad_crop_from_outside_shows_a_plain_message(source_preview):
    _window, bridge, _worker, _source, _warnings = source_preview
    bridge.review.setCrop(99, 0, 0, 5000, 5000)
    bridge.review.setCrop(1, 5000, 0, 5000, 5000)
    assert crop_of(bridge) is None
    assert bridge.bannerKind == "error"
    assert not any(ch.isdigit() for ch in bridge.bannerText)
