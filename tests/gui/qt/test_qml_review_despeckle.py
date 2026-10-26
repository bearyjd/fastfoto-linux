"""Remove specks in the real window: the form's box, the review page's box, the preview dialog."""

from dataclasses import replace

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import Qt
from PySide6.QtQml import QQmlProperty, qmlContext
from PySide6.QtTest import QTest

from fastfoto_linux.documents import CleanupPolicy, ColourMode, ColourPolicy
from fastfoto_linux.documents.auto_colour import ColourDecision, ColourReason
from fastfoto_linux.gui.review import ReviewState
from tests.gui.qt import test_qml_documents, test_qml_review_window
from tests.gui.qt.qt_helpers import child, click, invoke, settle
from tests.gui.qt.test_qml_review_cleanup import choose, deliver

pytestmark = pytest.mark.usefixtures("kirigami", "ocrmypdf_comes_with_the_app")

open_window = test_qml_documents.open_window
make_doc_bridge = test_qml_documents.make_doc_bridge
base_review_window = test_qml_review_window.review_window
GREY = ColourDecision(ColourMode.COLOUR, ColourMode.GREY, ColourReason.FAINT_MARKS)
BW = ColourDecision(ColourMode.COLOUR, ColourMode.BW, ColourReason.BILEVEL)
FORM_LABEL = "Remove specks (black and white pages)"  # the name is the visible label


@pytest.fixture
def despeckle_window(base_review_window):
    """The review page of three analysed pages: 1 and 2 grey, 3 black and white."""
    window, bridge, worker, source, warnings = base_review_window
    pages = tuple(
        replace(page, colour=decision)
        for page, decision in zip(source.pages, (GREY, GREY, BW), strict=True)
    )
    source = replace(source, pages=pages)
    side = bridge.controller.review
    side._settings = replace(side._settings, colour=ColourPolicy.AUTO)
    side.state = ReviewState(source)
    bridge.review.refresh()
    settle()
    return window, bridge, worker, source, warnings


def accessible_name(item):
    return QQmlProperty(item, "Accessible.name", qmlContext(item)).read()


def draft_of(bridge):
    return bridge.controller.review.state.draft


def open_output_preview(window, bridge, worker, number):
    """Open that page's dialog on its output view and return the request sent."""
    child(window, "reviewGrid").setProperty("currentIndex", number - 1)
    bridge.review.focus(number)
    invoke(child(window, "reviewGrid"), "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Return)
    choose(child(window, "reviewPreviewViewBox"), 1)
    request = worker.calls[-1][1][0]
    assert request.view == "output" and request.number == number
    return request


# -- the Documents form --------------------------------------------------------------------------


def test_the_form_has_the_box_under_the_cleanup_box_and_it_sets_the_field(
    make_doc_bridge, open_window
):
    bridge = make_doc_bridge()
    window, warnings = open_window(bridge)
    box = child(window, "docDespeckleBox")
    assert box.property("text") == FORM_LABEL
    assert accessible_name(box) == FORM_LABEL
    assert box.property("enabled") and box.property("checked") is False
    click(box)
    settle()
    assert bridge.controller.document_form.despeckle is True
    assert box.property("checked") is True
    bridge.setDocumentField("despeckle", False)
    settle()
    assert box.property("checked") is False
    assert warnings == []


def test_the_box_follows_the_form_it_is_opened_on(make_doc_bridge, open_window):
    bridge = make_doc_bridge()
    bridge.setDocumentField("despeckle", True)
    window, _warnings = open_window(bridge)
    assert child(window, "docDespeckleBox").property("checked") is True


def test_the_cleanup_hint_is_unchanged_and_one_sentence_explains_the_box(
    make_doc_bridge, open_window
):
    window, _warnings = open_window(make_doc_bridge())
    hint = child(window, "docCleanupHint").property("text")
    assert hint.startswith("Off by default.") and hint.endswith("in the review preview.")
    assert "black-and-white pages are not changed" in hint
    assert child(window, "docDespeckleHint").property("text") == (
        "Remove specks deletes tiny isolated dots from black-and-white pages; "
        "dots near text are kept."
    )


# -- the review page -----------------------------------------------------------------------------


def test_the_review_page_box_is_a_document_switch(despeckle_window):
    window, bridge, _worker, _source, warnings = despeckle_window
    box = child(window, "reviewDespeckleBox")
    assert box.property("text") == accessible_name(box) == "Remove specks for the document"
    assert box.property("checked") is False and bridge.review.documentDespeckle is False
    click(box)
    settle()
    assert draft_of(bridge).despeckle is True
    assert bridge.review.documentDespeckle is True and box.property("checked") is True
    assert bridge.controller.review.dirty
    bridge.review.setDocumentDespeckle(False)
    settle()
    assert draft_of(bridge).despeckle is False and box.property("checked") is False
    assert warnings == []


def test_the_explanation_names_only_a_black_and_white_page(despeckle_window):
    window, bridge, _worker, _source, _warnings = despeckle_window
    bridge.review.setDocumentDespeckle(True)
    explanation = child(window, "reviewDespeckleExplanation")
    bridge.review.focus(1)
    settle()
    assert explanation.property("text") == ""
    child(window, "reviewGrid").setProperty("currentIndex", 2)
    bridge.review.focus(3)
    settle()
    assert explanation.property("text") == "Remove specks: on (document setting)"
    assert bridge.review.items.get(2)["despeckleText"] == "Remove specks: on (document setting)"
    assert bridge.review.items.get(0)["despeckleText"] == ""


def test_a_despeckle_change_refreshes_the_open_output_preview(despeckle_window):
    window, bridge, worker, source, _warnings = despeckle_window
    first = open_output_preview(window, bridge, worker, 3)
    deliver(bridge, source, first, "page-0003-output-bw-off-r0.jpg")
    before = len(worker.calls)
    click(child(window, "reviewDespeckleBox"))
    settle()
    assert len(worker.calls) == before + 1
    assert worker.calls[-1][1][0].draft.despeckle is True


# -- the preview dialog --------------------------------------------------------------------------


def test_the_cleanup_switch_is_enabled_on_a_bw_page_with_despeckle_on_and_cleanup_off(
    despeckle_window,
):
    window, bridge, worker, source, _warnings = despeckle_window
    first = open_output_preview(window, bridge, worker, 3)
    deliver(bridge, source, first, "page-0003-output-bw-off-r0.jpg")
    switch = child(window, "reviewPreviewCleanupSwitch")
    assert draft_of(bridge).cleanup is CleanupPolicy.OFF
    assert bridge.review.previewCleanupAvailable is False and not switch.property("enabled")
    bridge.review.setDocumentDespeckle(True)
    settle()
    assert bridge.review.previewCleanupAvailable is True and switch.property("enabled")


def test_a_grey_page_does_not_gain_the_switch_from_despeckle(despeckle_window):
    window, bridge, worker, source, _warnings = despeckle_window
    first = open_output_preview(window, bridge, worker, 1)
    deliver(bridge, source, first, "page-0001-output-grey-off-r0.jpg")
    bridge.review.setDocumentDespeckle(True)
    settle()
    assert bridge.review.previewCleanupAvailable is False


def test_the_label_says_specks_removed_on_the_cleaned_side_only(despeckle_window):
    window, bridge, worker, source, _warnings = despeckle_window
    bridge.review.setDocumentDespeckle(True)
    first = open_output_preview(window, bridge, worker, 3)
    deliver(bridge, source, first, "page-0003-output-bw-off-r0-s.jpg")
    assert bridge.review.previewLabel == "Output: Black and white — specks removed"
    label = child(window, "reviewPreviewKindLabel")
    assert label.property("text") == "Output: Black and white — specks removed"
    click(child(window, "reviewPreviewCleanupSwitch"))
    settle()
    second = worker.calls[-1][1][0]
    assert second.cleaned is False
    deliver(bridge, source, second, "page-0003-output-bw-off-r0.jpg")
    assert "specks removed" not in bridge.review.previewLabel


def test_the_label_is_unchanged_with_the_switch_off(despeckle_window):
    window, bridge, worker, source, _warnings = despeckle_window
    first = open_output_preview(window, bridge, worker, 3)
    deliver(bridge, source, first, "page-0003-output-bw-off-r0.jpg")
    assert bridge.review.previewLabel == "Output: Black and white"
