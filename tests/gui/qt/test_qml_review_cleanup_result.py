"""The review panel names the cleanup result of the previewed page, and only while it is current."""

import pytest

from tests.gui.qt import require_qt

require_qt()

from fastfoto_linux.documents import CleanupPolicy
from fastfoto_linux.documents.cleanup import CleanupStatus
from tests.gui.qt import test_qml_documents, test_qml_review_window
from tests.gui.qt.qt_helpers import child, click, settle
from tests.gui.qt.test_qml_review_cleanup import (  # noqa: F401  (fixtures)
    choose,
    cleanup_window,
    deliver,
    open_output_preview,
)

pytestmark = pytest.mark.usefixtures("kirigami", "ocrmypdf_comes_with_the_app")

open_window = test_qml_documents.open_window
base_review_window = test_qml_review_window.review_window
BASE = "Paper cleanup: Light requested (document setting)"


def explanation(window):
    return child(window, "reviewCleanupExplanation").property("text")


def dark(bridge, source, request):
    name = "page-0001-output-grey-light-r0.jpg"
    return deliver(bridge, source, request, name, status=CleanupStatus.DARK)


def light_preview(cleanup_window):  # noqa: F811
    window, bridge, worker, source, warnings = cleanup_window
    choose(child(window, "reviewDocumentCleanupBox"), 1)  # Light
    request = open_output_preview(window, bridge, worker)
    return window, bridge, worker, source, warnings, request


def test_the_panel_says_what_the_light_preview_did(cleanup_window):  # noqa: F811
    window, bridge, _worker, source, warnings, request = light_preview(cleanup_window)
    assert explanation(window) == BASE
    dark(bridge, source, request)
    assert explanation(window) == BASE + " — skipped: paper too dark"
    assert warnings == []


def test_a_level_change_before_the_next_preview_drops_the_result(cleanup_window):  # noqa: F811
    window, bridge, _worker, source, warnings, request = light_preview(cleanup_window)
    dark(bridge, source, request)
    bridge.review.setCleanup(1, "strong")
    settle()
    assert explanation(window) == "Paper cleanup: Strong requested (this page)"
    assert warnings == []


def test_a_stale_status_for_the_old_level_is_not_shown_even_if_it_lingers(cleanup_window):  # noqa: F811
    window, bridge, _worker, source, warnings, request = light_preview(cleanup_window)
    dark(bridge, source, request)
    side = bridge.controller.review
    # An edit that does not restart the preview leaves the old status behind.
    side.state = side.state.set_cleanup(1, CleanupPolicy.STRONG)
    bridge.review.refresh()
    settle()
    assert "skipped" not in explanation(window)
    assert warnings == []


def test_the_original_side_of_the_toggle_has_no_result(cleanup_window):  # noqa: F811
    window, bridge, _worker, source, warnings, request = light_preview(cleanup_window)
    dark(bridge, source, request)
    click(child(window, "reviewPreviewCleanupSwitch"))
    settle()
    assert explanation(window) == BASE
    assert warnings == []


def test_a_status_delivered_for_the_original_side_is_not_shown(cleanup_window):  # noqa: F811
    window, bridge, worker, source, warnings, request = light_preview(cleanup_window)
    dark(bridge, source, request)
    click(child(window, "reviewPreviewCleanupSwitch"))
    settle()
    original = worker.calls[-1][1][0]
    assert original.cleaned is False
    # The worker reports OFF for a render without cleanup; it must not read as a skip.
    name = "page-0001-output-grey-off-r0.jpg"
    deliver(bridge, source, original, name, status=CleanupStatus.OFF)
    assert explanation(window) == BASE
    assert warnings == []
