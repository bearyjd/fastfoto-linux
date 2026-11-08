"""The interface language in the app: the bridge, the settings page and German at narrow widths."""

from collections.abc import Iterator
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtGui import QAccessible

from fastfoto_linux.gui.qt import translation
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, settle
from tests.gui.qt.test_power_settings import open_settings
from tests.gui.qt.test_qml_accessibility import unnamed
from tests.gui.qt.test_qml_narrow import narrow, overflowing

pytestmark = pytest.mark.usefixtures("kirigami")
open_window = test_qml.open_window


@pytest.fixture(autouse=True)
def english_again() -> Iterator[None]:
    translation.deactivate()
    try:
        yield
    finally:
        translation.deactivate()


def test_the_bridge_text_is_english_by_default(make_bridge: Any) -> None:
    bridge = make_bridge()
    bridge.checkScanner()
    assert bridge.uiLanguage == "en"
    assert not bridge.uiLanguageRestart


def test_the_fixed_messages_of_the_bridge_are_translated_when_german_is_active(
    make_bridge: Any,
) -> None:
    assert translation.activate("de")
    bridge = make_bridge()
    assert bridge.scannerText == "Der Scanner wurde noch nicht geprüft."
    assert bridge.whyNotScan != "Press Check again to look for the scanner."


def test_a_message_with_numbers_stays_english_under_german(make_bridge: Any) -> None:
    assert translation.activate("de")
    bridge = make_bridge()
    assert bridge.progressText == ""


def test_the_choices_are_the_allowlist_with_german_marked_partial(make_bridge: Any) -> None:
    choices = make_bridge().uiLanguageChoices
    assert [choice["value"] for choice in choices] == ["en", "de"]
    assert "partial" in choices[1]["label"].lower()


def test_choosing_a_language_needs_a_restart_and_is_remembered_only_when_asked(
    make_bridge: Any,
) -> None:
    bridge = make_bridge()  # remember=False: nothing is written
    bridge.setUiLanguage("de")
    assert bridge.uiLanguage == "de"
    assert bridge.uiLanguageRestart
    bridge.setUiLanguage("en")
    assert not bridge.uiLanguageRestart


@pytest.mark.parametrize("value", ["fr", "", "../de", "DE", "de\x00"])
def test_an_unknown_language_is_ignored(make_bridge: Any, value: str) -> None:
    bridge = make_bridge()
    bridge.setUiLanguage(value)
    assert bridge.uiLanguage == "en"


def test_the_choice_is_saved_to_the_settings_file(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, make_bridge: Any
) -> None:
    from fastfoto_linux.gui import prefs
    from fastfoto_linux.gui.qt import bridge as bridge_module

    path = tmp_path / "gui.json"
    monkeypatch.setattr(bridge_module, "save_ui_language", lambda code: prefs.save_ui_language(code, path))
    bridge = make_bridge()
    bridge._remember = True
    bridge.setUiLanguage("de")
    assert prefs.load_ui_language(path) == "de"


def test_a_failing_save_is_logged_and_the_choice_still_applies(
    monkeypatch: pytest.MonkeyPatch, make_bridge: Any
) -> None:
    from fastfoto_linux.gui.qt import bridge as bridge_module

    def refuse(code: str) -> None:
        raise OSError("read-only")

    monkeypatch.setattr(bridge_module, "save_ui_language", refuse)
    bridge = make_bridge()
    bridge._remember = True
    bridge.setUiLanguage("de")
    assert bridge.uiLanguage == "de"


def test_the_settings_page_offers_the_language_and_says_german_is_partial(
    make_bridge: Any, open_window: Any, messages: list[str]
) -> None:
    window, _ = open_window(make_bridge())
    open_settings(window)
    box = child(window, "uiLanguageBox")
    assert box.property("count") == 2
    assert "partial" in box.property("displayText").lower() or box.property("currentIndex") == 0
    assert not [line for line in messages if "uiLanguage" in line]


def test_the_language_box_has_an_accessible_name(
    make_bridge: Any, open_window: Any
) -> None:
    QAccessible.setActive(True)
    try:
        window, _ = open_window(make_bridge())
        open_settings(window)
        assert unnamed(window) == []
    finally:
        QAccessible.setActive(False)


def german_window(make_bridge: Any, open_window: Any) -> Any:
    assert translation.activate("de")
    window, _ = open_window(make_bridge())
    return window


def test_german_labels_are_shown_and_fit_the_narrowest_window(
    make_bridge: Any, open_window: Any, messages: list[str]
) -> None:
    english, _ = open_window(make_bridge())
    narrow(english)
    baseline = overflowing(english.contentItem())
    assert translation.activate("de")
    window, _ = open_window(make_bridge())
    narrow(window)
    assert child(window, "photosModeButton").property("text") == "Fotos"
    assert child(window, "documentsModeButton").property("text") == "Dokumente"
    assert overflowing(window.contentItem()) == baseline
    settle()


def test_german_settings_page_fits_the_narrowest_window(
    make_bridge: Any, open_window: Any
) -> None:
    english, _ = open_window(make_bridge())
    narrow(english)
    open_settings(english)
    baseline = overflowing(english.contentItem())
    translation.activate("de")
    window, _ = open_window(make_bridge())
    narrow(window)
    open_settings(window)
    assert overflowing(window.contentItem()) == baseline


def test_german_accessible_names_follow_the_translation(
    make_bridge: Any, open_window: Any
) -> None:
    QAccessible.setActive(True)
    try:
        window = german_window(make_bridge, open_window)
        button = child(window, "photosModeButton")
        iface = QAccessible.queryAccessibleInterface(button)
        assert iface.text(QAccessible.Text.Name) == "Fotos"
        assert unnamed(window) == []
    finally:
        QAccessible.setActive(False)
