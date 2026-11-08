"""The interface language in the app: the bridge, the settings page and German at narrow widths."""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QObject, QPointF
from PySide6.QtGui import QAccessible

from fastfoto_linux.gui.qt import translation
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, settle
from tests.gui.qt.test_power_settings import open_settings
from tests.gui.qt.test_qml_accessibility import unnamed
from tests.gui.qt.test_qml_narrow import fits, narrow

pytestmark = pytest.mark.usefixtures("kirigami")
QML_DIR = Path(__file__).resolve().parents[3] / "src" / "fastfoto_linux" / "gui" / "qml"
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
    monkeypatch.setattr(
        bridge_module, "save_ui_language", lambda code: prefs.save_ui_language(code, path)
    )
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
    assert box.property("currentIndex") == 0
    assert not child(window, "uiLanguagePartialNote").property("visible")
    assert not child(window, "uiLanguageRestartNote").property("visible")
    assert not [line for line in messages if "uiLanguage" in line]


def test_choosing_german_shows_the_partial_note_and_the_restart_note(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    open_settings(window)
    bridge.setUiLanguage("de")
    settle()
    box = child(window, "uiLanguageBox")
    assert box.property("currentIndex") == 1
    assert "partial" in box.property("displayText").lower()
    assert child(window, "uiLanguagePartialNote").property("visible")
    assert child(window, "uiLanguageRestartNote").property("visible")


def test_the_language_box_has_an_accessible_name(make_bridge: Any, open_window: Any) -> None:
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


SCAN_ROW = (
    "modeSwitch",
    "photosModeButton",
    "documentsModeButton",
    "scannerChip",
    "checkAgainButton",
    "scanButton",
)
FORM_CONTROLS = tuple(
    sorted(
        set(
            re.findall(
                r'objectName: "(\w+)"',
                (QML_DIR / "FormPanel.qml").read_text(),
            )
        )
    )
)


def geometry(window: Any, names: tuple[str, ...]) -> dict[str, tuple[float, ...]]:
    found = {}
    for name in names:
        item = window.findChild(QObject, name)
        if hasattr(item, "mapToScene") and item.property("visible"):
            point = item.mapToScene(QPointF(0, 0))
            found[name] = (point.x(), point.y(), item.property("width"), item.property("height"))
    return found


def test_german_labels_are_shown_and_the_scan_row_fits_the_narrowest_window(
    make_bridge: Any, open_window: Any
) -> None:
    assert translation.activate("de")
    window, _ = open_window(make_bridge())
    narrow(window)
    assert child(window, "photosModeButton").property("text") == "Fotos"
    assert child(window, "documentsModeButton").property("text") == "Dokumente"
    assert child(window, "scanButton").property("text") == "Scannen"
    for name in SCAN_ROW:
        assert fits(child(window, name)), name


def test_german_does_not_move_a_single_control_of_the_form(
    make_bridge: Any, open_window: Any
) -> None:
    """The form keeps its English text, so no label of the pilot may displace any of its controls.

    (A longer label once changed an implicit width and pushed a form control aside.)
    """
    warm_up, _ = open_window(make_bridge())  # the first window loads icons; later ones are alike
    narrow(warm_up)
    english, _ = open_window(make_bridge())
    narrow(english)
    before = geometry(english, FORM_CONTROLS)
    assert len(before) >= 5
    assert translation.activate("de")
    german, _ = open_window(make_bridge())
    narrow(german)
    assert geometry(german, FORM_CONTROLS) == before


def test_german_settings_page_fits_the_narrowest_window(make_bridge: Any, open_window: Any) -> None:
    assert translation.activate("de")
    window, _ = open_window(make_bridge())
    narrow(window)
    open_settings(window)
    names = set(
        re.findall(r'objectName: "(\w+)"', (QML_DIR / "ScannerSettingsPage.qml").read_text())
    )
    shown = [
        name
        for name in sorted(names - {"scannerSettingsPage"})
        if (item := window.findChild(QObject, name)) and item.property("visible")
    ]
    assert "uiLanguageBox" in shown
    assert "powerBackButton" in shown
    page = child(window, "scannerSettingsPage")
    for name in shown:
        item = child(window, name)
        left = item.mapToItem(page, QPointF(0, 0)).x()
        assert left >= -1 and left + item.property("width") <= page.property("width") + 1, name


def test_german_accessible_names_follow_the_translation(make_bridge: Any, open_window: Any) -> None:
    QAccessible.setActive(True)
    try:
        window = german_window(make_bridge, open_window)
        button = child(window, "photosModeButton")
        iface = QAccessible.queryAccessibleInterface(button)
        assert iface.text(QAccessible.Text.Name) == "Fotos"
        assert unnamed(window) == []
    finally:
        QAccessible.setActive(False)
