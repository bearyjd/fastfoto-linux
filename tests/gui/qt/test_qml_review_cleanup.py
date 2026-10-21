"""Paper cleanup in the real window: the form, the review page choices and the preview dialog."""

from dataclasses import replace

import pytest

from tests.gui.qt import require_qt

require_qt()

from PIL import Image
from PySide6.QtCore import Q_ARG, QMetaObject, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlExpression, QQmlProperty, qmlContext
from PySide6.QtTest import QTest

from fastfoto_linux.documents import CleanupPolicy, ColourMode, ColourPolicy
from fastfoto_linux.documents.auto_colour import ColourDecision, ColourReason
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.gui.review import ReviewState
from fastfoto_linux.gui.reviewjobs import PreviewCompletion
from fastfoto_linux.session import DocumentSessionResult
from tests.gui.qt import test_qml_documents, test_qml_review_window
from tests.gui.qt.qt_helpers import child, click, invoke, settle, wait_until

pytestmark = pytest.mark.usefixtures("kirigami", "ocrmypdf_comes_with_the_app")

open_window = test_qml_documents.open_window
make_doc_bridge = test_qml_documents.make_doc_bridge
base_review_window = test_qml_review_window.review_window
LIGHT, STRONG, OFF = CleanupPolicy.LIGHT, CleanupPolicy.STRONG, CleanupPolicy.OFF
GREY_DECISION = ColourDecision(ColourMode.COLOUR, ColourMode.GREY, ColourReason.FAINT_MARKS)
BW_DECISION = ColourDecision(ColourMode.COLOUR, ColourMode.BW, ColourReason.BILEVEL)


@pytest.fixture
def cleanup_window(base_review_window):
    """The review page of three analysed pages: 1 and 2 grey, 3 black and white."""
    window, bridge, worker, source, warnings = base_review_window
    decisions = (GREY_DECISION, GREY_DECISION, BW_DECISION)
    source = replace(
        source,
        pages=tuple(
            replace(page, colour=decision)
            for page, decision in zip(source.pages, decisions, strict=True)
        ),
    )
    side = bridge.controller.review
    side._settings = replace(side._settings, colour=ColourPolicy.AUTO)
    side.state = ReviewState(source)
    bridge.review.refresh()
    settle()
    return window, bridge, worker, source, warnings


def accessible_name(item):
    return QQmlProperty(item, "Accessible.name", qmlContext(item)).read()


def choose(box, index):
    box.setProperty("currentIndex", index)
    assert QMetaObject.invokeMethod(box, "activated", Q_ARG(int, index))
    settle()


def draft_of(bridge):
    return bridge.controller.review.state.draft


def open_output_preview(window, bridge, worker):
    """Open page 1's dialog, switch it to the output view and return the request sent."""
    invoke(child(window, "reviewGrid"), "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Return)
    choose(child(window, "reviewPreviewViewBox"), 1)
    request = worker.calls[-1][1][0]
    assert request.view == "output"
    return request


def deliver(bridge, source, request, name, size=(40, 60)):
    path = source.raw_dir / "previews" / name
    path.parent.mkdir(exist_ok=True)
    Image.new("L", size, 128).save(path)
    bridge.controller.review.preview_ready(PreviewCompletion(request, path))
    settle()
    return path


# --- the Documents form -------------------------------------------------------------------------


def test_the_form_offers_off_light_strong_and_sets_the_field(make_doc_bridge, open_window):
    bridge = make_doc_bridge()
    window, warnings = open_window(bridge)
    box = child(window, "docCleanupBox")
    assert accessible_name(box) == "Paper cleanup"
    assert box.property("count") == 3
    assert box.property("currentValue") == "off"
    assert box.property("enabled")
    choose(box, 2)
    assert bridge.controller.document_form.cleanup == "strong"
    bridge.setDocumentField("cleanup", "light")
    settle()
    assert box.property("currentValue") == "light"
    hint = child(window, "docCleanupHint").property("text")
    assert hint.startswith("Off by default.")
    assert "black-and-white pages are not changed" in hint
    assert warnings == []


# --- the review page ----------------------------------------------------------------------------


def test_review_controls_exist_with_names(cleanup_window):
    window, _bridge, _worker, _source, warnings = cleanup_window
    document = child(window, "reviewDocumentCleanupBox")
    page = child(window, "reviewCleanupBox")
    assert accessible_name(document) == "Paper cleanup for the document"
    assert accessible_name(page) == "Selected page paper cleanup"
    assert (document.property("count"), page.property("count")) == (3, 4)
    assert document.property("currentValue") == "off"
    assert page.property("currentValue") == ""
    assert child(window, "reviewCleanupExplanation").property("text") == "Paper cleanup: off"
    assert warnings == []


def test_the_document_level_page_override_and_clearing_it(cleanup_window):
    window, bridge, _worker, _source, warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 1)
    assert draft_of(bridge).cleanup is LIGHT
    explanation = child(window, "reviewCleanupExplanation")
    assert explanation.property("text") == "Paper cleanup: Light (document setting)"
    page_box = child(window, "reviewCleanupBox")
    choose(page_box, 3)  # Strong for this page
    assert draft_of(bridge).edits[1].cleanup is STRONG
    assert draft_of(bridge).cleanup is LIGHT
    assert explanation.property("text") == "Paper cleanup: Strong (this page)"
    assert bridge.review.items.get(0)["cleanupOverride"] == "strong"
    assert bridge.review.items.get(1)["cleanupOverride"] == ""
    choose(page_box, 1)  # Off for this page beats the document level
    assert draft_of(bridge).edits[1].cleanup is OFF
    assert explanation.property("text") == "Paper cleanup: off"
    choose(page_box, 0)  # the document setting again: the override is gone
    assert draft_of(bridge).edits.get(1, PageEdit()).cleanup is None
    assert explanation.property("text") == "Paper cleanup: Light (document setting)"
    choose(child(window, "reviewDocumentCleanupBox"), 0)
    assert draft_of(bridge).cleanup is OFF
    assert page_box.property("currentValue") == ""
    assert warnings == []


def test_a_black_and_white_page_says_the_cleanup_is_not_used(cleanup_window):
    window, bridge, _worker, _source, _warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 2)
    child(window, "reviewGrid").setProperty("currentIndex", 2)
    bridge.review.focus(3)
    settle()
    text = child(window, "reviewCleanupExplanation").property("text")
    assert text == "Paper cleanup: not used for black and white output"


def test_the_choices_ride_the_sidecar_autosave(cleanup_window):
    window, bridge, _worker, _source, _warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 2)
    assert bridge.controller.review.dirty
    bridge.review.setCleanup(2, "light")
    assert draft_of(bridge).edits[2].cleanup is LIGHT
    bridge.review.setCleanup(2, "")
    assert draft_of(bridge).edits.get(2, PageEdit()).cleanup is None
    assert bridge.review.documentCleanup == "strong"


# --- the preview dialog -------------------------------------------------------------------------


def test_the_switch_toggles_between_cleaned_and_original_of_the_same_output(cleanup_window):
    window, bridge, worker, source, warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 2)
    first = open_output_preview(window, bridge, worker)
    assert first.cleaned is True and first.crop is None
    switch = child(window, "reviewPreviewCleanupSwitch")
    assert accessible_name(switch) == "Paper cleanup"
    assert switch.property("enabled") and switch.property("checked")
    cleaned = deliver(bridge, source, first, "page-0001-output-grey-strong-r0.jpg")
    image = child(window, "reviewPreviewImage")
    assert image.property("source").toLocalFile() == str(cleaned)
    assert "paper cleanup Strong" in child(window, "reviewPreviewKindLabel").property("text")
    click(switch)
    settle()
    second = worker.calls[-1][1][0]
    assert second.cleaned is False and second.view == "output"
    assert second.draft is first.draft
    assert image.property("source").isEmpty()
    # The answer for the cleaned side arrives late: it must not be shown for the original.
    bridge.controller.review.preview_ready(PreviewCompletion(first, cleaned))
    settle()
    assert image.property("source").isEmpty()
    original = deliver(bridge, source, second, "page-0001-output-grey-off-r0.jpg")
    assert image.property("source").toLocalFile() == str(original)
    assert "without paper cleanup" in child(window, "reviewPreviewKindLabel").property("text")
    assert not switch.property("checked")
    click(switch)
    settle()
    third = worker.calls[-1][1][0]
    assert third.cleaned is True
    assert image.property("source").isEmpty()
    assert warnings == []


def test_the_switch_is_disabled_when_the_page_has_no_cleanup_to_show(cleanup_window):
    window, bridge, worker, source, _warnings = cleanup_window
    first = open_output_preview(window, bridge, worker)  # document level is off
    deliver(bridge, source, first, "page-0001-output-grey-off-r0.jpg")
    switch = child(window, "reviewPreviewCleanupSwitch")
    assert not switch.property("enabled")
    assert bridge.review.previewCleanupAvailable is False
    bridge.review.setCleanup(1, "light")
    settle()
    assert bridge.review.previewCleanupAvailable is True
    assert switch.property("enabled")


def test_a_black_and_white_page_never_offers_the_switch(cleanup_window):
    window, bridge, worker, _source, _warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 2)
    child(window, "reviewGrid").setProperty("currentIndex", 2)
    bridge.review.focus(3)
    invoke(child(window, "reviewGrid"), "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Return)
    choose(child(window, "reviewPreviewViewBox"), 1)
    assert worker.calls[-1][1][0].number == 3
    assert not child(window, "reviewPreviewCleanupSwitch").property("enabled")


def test_a_document_level_change_refreshes_the_open_output_preview(cleanup_window):
    window, bridge, worker, source, _warnings = cleanup_window
    first = open_output_preview(window, bridge, worker)
    deliver(bridge, source, first, "page-0001-output-grey-off-r0.jpg")
    before = len(worker.calls)
    choose(child(window, "reviewDocumentCleanupBox"), 1)
    assert len(worker.calls) == before + 1
    assert worker.calls[-1][1][0].draft.cleanup is LIGHT


def painted_point(window, fraction_x, fraction_y):
    """The scene position at a fraction of the painted rectangle of the fitted preview."""
    image = child(window, "reviewPreviewImage")
    area = child(window, "reviewPreviewPickArea")
    wait_until(lambda: image.property("paintedWidth") > 0, "the preview image to load")
    painted_w, painted_h = image.property("paintedWidth"), image.property("paintedHeight")
    origin = area.mapToScene(QPointF(0, 0))
    left = origin.x() + (area.width() - painted_w) / 2
    top = origin.y() + (area.height() - painted_h) / 2
    return QPointF(left + fraction_x * painted_w, top + fraction_y * painted_h)


def test_clicking_the_page_asks_for_that_spot_at_actual_pixels(cleanup_window):
    window, bridge, worker, source, warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 1)
    first = open_output_preview(window, bridge, worker)
    deliver(bridge, source, first, "page-0001-output-grey-light-r0.jpg", size=(400, 600))
    assert child(window, "reviewPreviewCropHint").property("text") == (
        "Click the page to inspect that spot at actual pixels."
    )
    point = painted_point(window, 0.25, 0.75)
    QTest.mouseClick(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point.toPoint()
    )
    settle()
    request = worker.calls[-1][1][0]
    assert request.cleaned is True
    assert abs(request.crop[0] - 250) <= 3 and abs(request.crop[1] - 750) <= 3
    assert bridge.review.previewActual is True
    assert abs(bridge.review.previewCropX - 250) <= 3
    assert abs(bridge.review.previewCropY - 750) <= 3
    assert warnings == []


def test_the_pick_clamps_outside_the_painted_rectangle(cleanup_window):
    window, bridge, worker, source, _warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 1)
    first = open_output_preview(window, bridge, worker)
    deliver(bridge, source, first, "page-0001-output-grey-light-r0.jpg", size=(400, 300))
    point = painted_point(window, -0.5, 1.4)
    area = child(window, "reviewPreviewPickArea")
    origin = area.mapToScene(QPointF(0, 0))
    inside = QPointF(
        min(max(point.x(), origin.x() + 1), origin.x() + area.width() - 1),
        min(max(point.y(), origin.y() + 1), origin.y() + area.height() - 1),
    )
    QTest.mouseClick(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, inside.toPoint()
    )
    settle()
    crop = worker.calls[-1][1][0].crop
    assert crop is not None and all(0 <= value <= 1000 for value in crop)


def test_actual_pixels_show_an_uncapped_crop_and_hide_the_fitted_image(cleanup_window):
    window, bridge, worker, source, warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 1)
    first = open_output_preview(window, bridge, worker)
    deliver(bridge, source, first, "page-0001-output-grey-light-r0.jpg", size=(400, 600))
    fitted = child(window, "reviewPreviewImage")
    flick = child(window, "reviewPreviewCropFlick")
    crop_image = child(window, "reviewPreviewCropImage")
    assert not flick.property("visible")
    assert fitted.property("visible")
    switch = child(window, "reviewPreviewActualSwitch")
    assert accessible_name(switch) == "Actual pixels"
    click(switch)
    settle()
    request = worker.calls[-1][1][0]
    assert request.crop == (500, 500) and request.cleaned is True
    crop = deliver(bridge, source, request, "page-0001-output-grey-light-r0-crop.png", (2000, 1500))
    assert flick.property("visible")
    assert not fitted.property("visible")
    assert crop_image.property("source").toLocalFile() == str(crop)
    wait_until(lambda: crop_image.property("width") > 0, "the crop to load")
    size = crop_image.property("sourceSize")  # not capped at the fitted image's 1600
    assert (size.width(), size.height()) == (2000, 1500)
    assert (crop_image.property("width"), crop_image.property("height")) == (2000, 1500)
    pad = QQmlExpression(qmlContext(crop_image), crop_image, "fillMode === Image.Pad")
    assert pad.evaluate()[0] is True  # one image pixel is one screen pixel
    assert "actual pixels" in child(window, "reviewPreviewKindLabel").property("text")
    click(switch)
    settle()
    assert worker.calls[-1][1][0].crop is None
    assert warnings == []


def test_the_dialog_for_the_source_view_hides_the_cleanup_controls(cleanup_window):
    window, _bridge, _worker, _source, _warnings = cleanup_window
    invoke(child(window, "reviewGrid"), "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Return)
    for name in (
        "reviewPreviewCleanupSwitch",
        "reviewPreviewActualSwitch",
        "reviewPreviewCropHint",
    ):
        assert not child(window, name).property("visible")


def test_reopening_a_past_scan_starts_with_cleanup_off(cleanup_window):
    window, bridge, worker, source, _warnings = cleanup_window
    bridge.setDocumentField("cleanup", "strong")
    bridge.review.openFolder(QUrl.fromLocalFile(str(source.raw_dir)))
    settings = worker.calls[-1][1][1]
    assert worker.calls[-1][0] == "analyse"
    assert settings.cleanup is OFF
    bridge.controller.on_finished(
        DocumentSessionResult(draft=replace(source, cleanup=OFF), raw_dir=source.raw_dir)
    )
    settle()
    assert child(window, "reviewDocumentCleanupBox").property("currentValue") == "off"
