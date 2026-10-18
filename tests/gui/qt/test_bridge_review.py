"""The review interface exposes edits, naming and debounced autosave to QML."""

from tests.gui.qt import require_qt

require_qt()

from fastfoto_linux.gui import reviewside
from fastfoto_linux.gui.qt.review_view import ReviewView
from fastfoto_linux.gui.state import Mode
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult, Stage
from tests.gui.doc_helpers import DocFakeWorker
from tests.gui.qt.qt_helpers import wait_until
from tests.gui.review_helpers import draft


def open_review(make_bridge, out):
    bridge = make_bridge(mode=Mode.DOCUMENTS)
    bridge.controller._worker = DocFakeWorker()
    view = ReviewView(bridge)
    view.enable()
    bridge.controller.check_scanner()
    bridge.controller.on_scanner(None)
    bridge.controller.start_scan()
    bridge.controller.on_stage(Stage.PROCESSING)
    bridge.controller.on_finished(
        DocumentSessionResult(draft=draft(out), raw_dir=out, raw_reason=DocumentRawReason.REVIEW)
    )
    view.refresh()
    return bridge, view


def test_review_interface_edits_names_and_summary(make_bridge, out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    bridge, view = open_review(make_bridge, out)
    assert view.active
    assert view.items.rowCount() == 3
    assert view.canSave
    view.toggle(2)
    view.rotate(3, 1)
    view.toggleSplit(3)
    view.setPartName(2, "Other")
    assert view.parts[1]["name"] == "Other"
    assert "2 PDFs" in view.summary
    view.setFlaggedOnly(True)
    assert view.items.rowCount() == 1
    view.focus(3)
    assert view.focusNumber == 3
    assert view.rawRootUrl.endswith("/.raw")
    assert bridge.review is not None


def test_edits_debounce_and_flush_saves_the_latest_snapshot(make_bridge, out, monkeypatch):
    saved = []
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: saved.append(args[0]))
    _bridge, view = open_review(make_bridge, out)
    view.toggle(2)
    view.rotate(3, 1)
    assert saved == []
    assert view.flush()
    assert len(saved) == 1
    assert saved[0].edits[3].quarter_turns == 1
    view.rotate(3, 1)
    wait_until(lambda: len(saved) == 2, "debounced review autosave")
    assert saved[-1].edits[3].quarter_turns == 2


def test_close_flushes_a_pending_review_edit(make_bridge, out, monkeypatch):
    saved = []
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: saved.append(args[0]))
    bridge, view = open_review(make_bridge, out)
    view.rotate(3, 1)
    assert bridge.requestClose()
    assert len(saved) == 1


def test_failed_autosave_vetoes_window_close(make_bridge, out, monkeypatch):
    def fail(*args):
        raise OSError("full")

    monkeypatch.setattr(reviewside, "save_draft", fail)
    bridge, view = open_review(make_bridge, out)
    view.rotate(3, 1)
    assert not bridge.requestClose()
    assert view.active
