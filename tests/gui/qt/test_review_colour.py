"""Real Qt roles, selected-page choices, reopen and truthful asynchronous output previews."""

import pytest

from tests.gui.qt import require_qt

require_qt()

from PIL import Image
from PySide6.QtCore import Q_ARG, QMetaObject, Qt
from PySide6.QtTest import QSignalSpy, QTest

from fastfoto_linux.documents import ColourPolicy
from fastfoto_linux.documents.draft_store import open_draft
from fastfoto_linux.gui.qt.review_model import ReviewModel
from fastfoto_linux.gui.review import ReviewState, review_items
from fastfoto_linux.gui.reviewjobs import PreviewCompletion
from tests.gui.qt import test_qml_documents, test_qml_review_window
from tests.gui.qt.qt_helpers import child, invoke, settle
from tests.gui.qt.test_bridge_review import open_review
from tests.gui.test_review_colour import decided_draft

open_window = test_qml_documents.open_window
make_doc_bridge = test_qml_documents.make_doc_bridge
review_window = test_qml_review_window.review_window


def test_model_has_explicit_colour_roles_and_updates_without_reset(qapp, out):
    model = ReviewModel()
    roles = {bytes(name).decode() for name in model.roleNames().values()}
    assert roles >= {"colourPolicy", "colourMode", "colourReason", "colourOverride", "colourText"}
    state = ReviewState(decided_draft(out))
    model.set_items(review_items(state, ColourPolicy.AUTO))
    reset, changed = QSignalSpy(model.modelReset), QSignalSpy(model.dataChanged)
    model.set_items(review_items(state.set_colour(1, ColourPolicy.BW), ColourPolicy.AUTO))
    assert changed.count() == 1
    assert reset.count() == 0
    assert model.get(0)["colourMode"] == "bw"
    assert model.get(0)["colourOverride"] == "bw"


def test_qt_slot_sets_clears_and_autosaves_only_the_selected_raw_page(make_bridge, out):
    bridge, view = open_review(make_bridge, out)
    view.setColour(2, "auto")
    assert bridge.controller.review.state.draft.edits[2].colour is ColourPolicy.AUTO
    assert view.items.get(1)["colourOverride"] == "auto"
    assert view.items.get(0)["colourOverride"] == ""
    view.setColour(2, "")
    assert bridge.controller.review.state.draft.edits[2].colour is None


@pytest.mark.usefixtures("kirigami")
def test_document_form_adds_auto_by_value_and_keeps_colour_default(make_doc_bridge, open_window):
    bridge = make_doc_bridge()
    window, warnings = open_window(bridge)
    box = child(window, "docColourBox")
    assert box.property("count") == 4
    assert box.property("currentValue") == "colour"
    bridge.setDocumentField("colour", "auto")
    settle()
    assert box.property("currentValue") == "auto"
    assert warnings == []


def test_real_selected_page_override_survives_flush_and_reopen(review_window):
    window, bridge, _worker, source, warnings = review_window
    box = child(window, "reviewColourBox")
    assert box.property("count") == 5
    assert box.property("currentValue") == ""
    child(window, "reviewGrid").setProperty("currentIndex", 2)
    bridge.review.focus(3)
    settle()
    box.setProperty("currentIndex", 1)
    assert QMetaObject.invokeMethod(box, "activated", Q_ARG(int, 1))
    settle()
    state = bridge.controller.review.state
    assert state.draft.edits[3].colour is ColourPolicy.AUTO
    assert 1 not in state.draft.edits
    assert bridge.review.flush()
    settings = bridge.controller.review._settings
    reopened = open_draft(
        source.raw_dir, tuple(source.raw_dir / page.name for page in source.pages), settings
    )
    assert reopened.edits[3].colour is ColourPolicy.AUTO
    bridge.controller.review._accept(reopened)
    child(window, "reviewGrid").setProperty("currentIndex", 2)
    bridge.review.focus(3)
    settle()
    assert box.property("currentValue") == "auto"
    assert warnings == []


def test_real_preview_keeps_source_label_until_current_output_arrives(review_window):
    window, bridge, worker, source, warnings = review_window
    grid = child(window, "reviewGrid")
    invoke(grid, "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Return)
    selector = child(window, "reviewPreviewViewBox")
    assert selector.property("currentValue") == "source"
    assert child(window, "reviewPreviewKindLabel").property("text") == "Source preview"
    selector.setProperty("currentIndex", 1)
    assert QMetaObject.invokeMethod(selector, "activated", Q_ARG(int, 1))
    old_request = worker.calls[-1][1][0]
    assert old_request.view == "output"
    image = child(window, "reviewPreviewImage")
    assert image.property("source").isEmpty()
    bridge.review.setColour(1, "bw")
    bridge.review.previewMode(1, "output")
    current = worker.calls[-1][1][0]
    assert current.draft is not old_request.draft
    output = source.raw_dir / "previews" / "page-0001-output-bw.jpg"
    output.parent.mkdir(exist_ok=True)
    Image.new("L", (40, 60), 0).save(output)
    bridge.controller.review.preview_ready(PreviewCompletion(old_request, output))
    settle()
    assert image.property("source").isEmpty()
    bridge.controller.review.preview_ready(PreviewCompletion(current, output))
    settle()
    assert image.property("source").toLocalFile() == str(output)
    assert "Output" in child(window, "reviewPreviewKindLabel").property("text")
    assert "Black and white" in child(window, "reviewPreviewKindLabel").property("text")
    assert warnings == []
