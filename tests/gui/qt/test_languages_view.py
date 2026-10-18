"""Language lookup/download jobs never block Qt, change saved order, or download implicitly."""

import threading
from dataclasses import replace
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from fastfoto_linux.documents import OcrCancelledError
from fastfoto_linux.documents.ocr_languages import Inventory, Language
from fastfoto_linux.gui.qt.languages_view import LanguagesView
from tests.gui.qt.qt_helpers import settle, wait_until


@pytest.fixture
def make_languages(make_bridge: Any):
    made: list[LanguagesView] = []

    def make(**tools: Any) -> LanguagesView:
        bridge = make_bridge()
        view = LanguagesView(bridge.controller, bridge, **tools)
        made.append(view)
        return view

    yield make
    for view in made:
        view.stop()


def test_discovery_is_local_asynchronous_and_keeps_saved_selection(make_languages: Any) -> None:
    entered, release = threading.Event(), threading.Event()
    called: list[int] = []

    def discover(**options: Any) -> Inventory:
        called.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return Inventory((Language("eng", "English", 100, installed=True),))

    view = make_languages(discover=discover, download=lambda *_a, **_k: pytest.fail("network"))
    try:
        view.reload()
        assert entered.wait(2)
        assert view.busy is True
        assert not view.ready
        assert called == [called[0]] and called[0] != threading.get_ident()
    finally:
        release.set()
    wait_until(lambda: not view.busy, "local languages")
    assert view.ready
    assert view.rows[0]["selected"]


def test_download_is_explicit_selected_only_and_updates_offline_status(make_languages: Any) -> None:
    inventory = Inventory(
        (Language("eng", "English", 100, installed=True), Language("spa", "Spanish", 200))
    )
    calls: list[tuple[str, ...]] = []

    def download(codes: tuple[str, ...], **options: Any) -> None:
        nonlocal inventory
        assert threading.current_thread() is not threading.main_thread()
        calls.append(tuple(codes))
        options["progress"]("spa", 100, 200)
        inventory = Inventory(tuple(replace(row, installed=True) for row in inventory.languages))

    view = make_languages(discover=lambda **_k: inventory, download=download)
    view.reload()
    wait_until(lambda: not view.busy, "languages")
    assert calls == []
    view.setSelected("spa", True)
    assert not view.ready
    assert view.canDownload
    assert "200" in view.downloadText
    view.downloadSelected()
    wait_until(lambda: not view.busy, "download")
    assert calls == [("spa",)]
    assert view.ready
    assert not view.canDownload
    assert all(row["installed"] for row in view.rows)


def test_cancel_then_retry_preserves_selection_and_disables_edits(make_languages: Any) -> None:
    started = threading.Event()
    attempts: list[tuple[str, ...]] = []
    inventory = Inventory((Language("eng", "English", 100),))

    def download(codes: tuple[str, ...], **options: Any) -> None:
        attempts.append(tuple(codes))
        started.set()
        assert options["cancel"].wait(5)
        raise OcrCancelledError("Cancelled")

    view = make_languages(discover=lambda **_k: inventory, download=download)
    view.reload()
    wait_until(lambda: not view.busy, "languages")
    view.downloadSelected()
    assert started.wait(2)
    view.setSelected("eng", False)
    assert view.rows[0]["selected"]
    view.cancel()
    wait_until(lambda: not view.busy, "cancelled download")
    assert "cancel" in view.message.lower()
    assert view.canDownload
    view.downloadSelected()
    wait_until(lambda: len(attempts) == 2, "retry")
    view.cancel()
    wait_until(lambda: not view.busy, "retry cancellation")
    assert attempts == [("eng",), ("eng",)]


def test_discovery_failure_is_a_visible_retryable_error(make_languages: Any) -> None:
    def discover(**options: Any) -> Inventory:
        raise OSError("Language data unavailable")

    view = make_languages(discover=discover, download=lambda *_a, **_k: None)
    view.reload()
    wait_until(lambda: not view.busy, "failed discovery")
    assert not view.ready
    assert "Language data unavailable" in view.message


def test_catalog_downloads_work_before_tesseract_is_installed(make_languages: Any) -> None:
    inventory = Inventory((Language("eng", "English", 100),), error="Tesseract is not installed.")
    calls: list[tuple[str, ...]] = []
    view = make_languages(
        discover=lambda **_k: inventory,
        download=lambda codes, **_k: calls.append(tuple(codes)),
    )
    view.reload()
    wait_until(lambda: not view.busy, "catalog without Tesseract")
    assert view.canDownload
    assert not view.ready
    assert "Tesseract" in view.scanMessage
    view.downloadSelected()
    wait_until(lambda: not view.busy, "advance download")
    assert calls == [("eng",)]
    assert not view.ready


def test_stopping_a_discovery_prevents_late_qt_updates(make_languages: Any) -> None:
    started, returned = threading.Event(), threading.Event()

    def discover(**options: Any) -> Inventory:
        started.set()
        assert options["cancel"].wait(5)
        returned.set()
        return Inventory((Language("eng", "English", 100, installed=True),))

    view = make_languages(discover=discover, download=lambda *_a, **_k: None)
    view.reload()
    assert started.wait(2)
    view.stop()
    assert returned.wait(2)
    settle()
    assert not view.ready
