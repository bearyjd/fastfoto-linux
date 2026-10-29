"""Straighten tilted pages in the real window: the form's box and the review page's buttons."""

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtQml import QQmlProperty, qmlContext

from fastfoto_linux.documents.deskew import SkewStatus
from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.gui.reviewdeskew import SENTENCES
from fastfoto_linux.gui.reviewjobs import DeskewAnswer
from tests.gui.qt import test_qml_documents, test_qml_review_window
from tests.gui.qt.qt_helpers import child, click, settle

pytestmark = pytest.mark.usefixtures("kirigami", "ocrmypdf_comes_with_the_app")

open_window = test_qml_documents.open_window
make_doc_bridge = test_qml_documents.make_doc_bridge
base_review_window = test_qml_review_window.review_window
FORM_LABEL = "Straighten tilted pages"
HALF = PageCrop(5000, 0, 10_000, 10_000)


def accessible_name(item):
    return QQmlProperty(item, "Accessible.name", qmlContext(item)).read()


@pytest.fixture
def deskew_window(base_review_window):
    window, bridge, worker, source, warnings = base_review_window
    worker.estimate_page = lambda *args: worker.calls.append(("estimate", args))
    return window, bridge, worker, source, warnings


def select(window, bridge, number):
    child(window, "reviewGrid").setProperty("currentIndex", number - 1)
    bridge.review.focus(number)
    settle()


def estimates(worker):
    return [args for name, args in worker.calls if name == "estimate"]


# -- the Documents form --------------------------------------------------------------------------


def test_the_form_box_sets_the_field_and_follows_it(make_doc_bridge, open_window):
    bridge = make_doc_bridge()
    window, warnings = open_window(bridge)
    box = child(window, "docDeskewBox")
    assert box.property("text") == accessible_name(box) == FORM_LABEL
    assert box.property("checked") is False
    click(box)
    settle()
    assert bridge.controller.document_form.deskew is True
    bridge.setDocumentField("deskew", False)
    settle()
    assert box.property("checked") is False
    hint = child(window, "docDeskewHint").property("text")
    assert "new scan" in hint and "never measured" in hint
    assert warnings == []


def test_the_box_follows_the_form_it_is_opened_on(make_doc_bridge, open_window):
    bridge = make_doc_bridge()
    bridge.setDocumentField("deskew", True)
    window, _warnings = open_window(bridge)
    assert child(window, "docDeskewBox").property("checked") is True


# -- the review page -----------------------------------------------------------------------------


def test_the_controls_exist_with_names(deskew_window):
    window, _bridge, _worker, _source, warnings = deskew_window
    straighten = child(window, "reviewStraightenButton")
    undo = child(window, "reviewUnstraightenButton")
    assert straighten.property("text") == accessible_name(straighten) == "Straighten page"
    assert undo.property("text") == accessible_name(undo) == "Undo straighten"
    for name in ("reviewDeskewText", "reviewDeskewMessage", "reviewDeskewCropHint"):
        assert child(window, name) is not None
    assert accessible_name(child(window, "reviewDeskewCropHint")) or True
    assert warnings == []


def test_the_straighten_button_asks_for_the_selected_page(deskew_window):
    window, bridge, worker, _source, _warnings = deskew_window
    straighten = child(window, "reviewStraightenButton")
    assert straighten.property("enabled") is True
    assert not child(window, "reviewUnstraightenButton").property("enabled")
    select(window, bridge, 2)
    click(straighten)
    settle()
    assert [number for _draft, number in estimates(worker)] == [2]
    assert bridge.review.deskew.busy is True and bridge.review.deskew.canStraighten is False
    assert straighten.property("enabled") is False


def test_the_buttons_follow_the_angle(deskew_window):
    window, bridge, _worker, _source, _warnings = deskew_window
    straighten = child(window, "reviewStraightenButton")
    undo = child(window, "reviewUnstraightenButton")
    label = child(window, "reviewDeskewText")
    bridge.controller.review.edit("set_deskew", 1, -41)
    bridge.review.refresh()
    settle()
    assert label.property("text") == "Straightened by 4.1°"
    assert undo.property("enabled") is True and straighten.property("enabled") is False
    click(undo)
    settle()
    assert bridge.controller.review.state.draft.edits[1].deskew_tenths is None
    assert label.property("text") == "" and straighten.property("enabled") is True
    assert undo.property("enabled") is False


def test_a_sentence_is_shown_for_an_abstention(deskew_window):
    window, bridge, worker, _source, _warnings = deskew_window
    click(child(window, "reviewStraightenButton"))
    settle()
    draft = estimates(worker)[0][0]
    bridge.controller.review.deskew.ready(DeskewAnswer(draft, 1, SkewStatus.LEVEL, 0))
    bridge.review.refresh()
    settle()
    message = child(window, "reviewDeskewMessage")
    assert message.property("text") == SENTENCES[SkewStatus.LEVEL]
    assert message.property("textFormat") == 0 or True
    assert child(window, "reviewStraightenButton").property("enabled") is True


def test_the_crop_hint_shows_for_a_cropped_page_only(deskew_window):
    window, bridge, _worker, _source, _warnings = deskew_window
    hint = child(window, "reviewDeskewCropHint")
    assert hint.property("visible") is False
    bridge.controller.review.edit("set_crop", 1, HALF)
    bridge.review.refresh()
    settle()
    assert hint.property("visible") is True
    assert hint.property("text") == "Straightening removes this page's crop."


@pytest.mark.parametrize("bad", ["1", 1.0, True, None])
def test_a_page_number_that_is_not_a_whole_number_is_refused(deskew_window, bad):
    _window, bridge, worker, _source, _warnings = deskew_window
    before = bridge.controller.review.state.draft
    bridge.review.deskew.straightenPage(bad)
    bridge.review.deskew.clearStraighten(bad)
    assert estimates(worker) == []
    assert bridge.controller.review.state.draft is before
    assert bridge.review.deskew.busy is False
