"""The desktop app hides two known-harmless KDE console lines and nothing else (no Qt needed)."""

from types import SimpleNamespace
from typing import Any

import pytest

from fastfoto_linux.gui.qt.messages import filtering_handler, is_known_noise
from fastfoto_linux.session.raw import TEMP_PREFIX

KDE_MENU_ITEM = "qrc:/qt/qml/org/kde/desktop/MenuItem.qml"
SHORTCUT_TEXT = (
    f"{KDE_MENU_ITEM}:85:13: QML Shortcut: Shortcut: Only binding to one of multiple key bindings "
    "associated with 9. Use 'sequences: [ <key> ]' to bind to all of them."
)
KDIRMODEL = "kf.kio.widgets.kdirmodel"


def removed(folder: str) -> str:
    return f'No node found for item that was just removed: QUrl("file:///photos/album/{folder}")'


def context(category: str | None = "default", file: str | None = None) -> Any:
    return SimpleNamespace(category=category, file=file, line=0, function=None)


# -- the two lines that are hidden ---------------------------------------------------------------


def test_the_shortcut_warning_of_the_kde_menu_item_is_noise() -> None:
    assert is_known_noise("default", KDE_MENU_ITEM, SHORTCUT_TEXT)


def test_the_shortcut_warning_is_noise_whether_the_style_is_compiled_in_or_a_file() -> None:
    path = "file:///usr/lib64/qt6/qml/org/kde/desktop/MenuItem.qml"
    assert is_known_noise("default", path, SHORTCUT_TEXT)


def test_the_removed_temp_folder_line_of_the_kde_folder_dialog_is_noise() -> None:
    assert is_known_noise(KDIRMODEL, None, removed(f"{TEMP_PREFIX}ab12cd"))


# -- near misses are passed through --------------------------------------------------------------


@pytest.mark.parametrize(
    "file",
    [
        "qrc:/qt/qml/org/kde/desktop/Button.qml",
        "qrc:/qt/qml/org/kde/other/MenuItem.qml",
        "file:///app/MenuItem.qml",
        "qrc:/qt/qml/org/kde/desktop/MenuItem.qml.bak",
        "",
        None,
    ],
    ids=["other-item", "other-style", "other-folder", "other-suffix", "empty", "none"],
)
def test_the_same_shortcut_text_from_another_file_is_not_noise(file: str | None) -> None:
    assert not is_known_noise("default", file, SHORTCUT_TEXT)


def test_another_warning_of_the_kde_menu_item_is_not_noise() -> None:
    text = f"{KDE_MENU_ITEM}:12:5: QML MenuItem: Cannot read property 'text' of null"
    assert not is_known_noise("default", KDE_MENU_ITEM, text)


@pytest.mark.parametrize(
    "folder",
    [
        "Holiday",
        ".raw",
        "ffscan-raw-ab12cd",  # not hidden
        f"x{TEMP_PREFIX}ab12cd",
        f"{TEMP_PREFIX}ab12cd/inner",  # the folder is not the one that was removed
    ],
    ids=["visible", "kept-raw", "no-dot", "not-a-prefix", "inside-the-temp-folder"],
)
def test_a_removed_item_that_is_not_the_temp_folder_is_not_noise(folder: str) -> None:
    assert not is_known_noise(KDIRMODEL, None, removed(folder))


def test_the_removed_item_text_in_another_category_is_not_noise() -> None:
    assert not is_known_noise("default", None, removed(f"{TEMP_PREFIX}ab12cd"))
    assert not is_known_noise(None, None, removed(f"{TEMP_PREFIX}ab12cd"))


@pytest.mark.parametrize(
    "text",
    [
        'No node found for item that was just added: QUrl("file:///a/.ffscan-raw-ab12cd")',
        "No node found for item that was just removed",
        "No node found for item that was just removed: .ffscan-raw-ab12cd",
        f'Other text: QUrl("file:///a/{TEMP_PREFIX}ab12cd")',
    ],
    ids=["added", "no-url", "no-qurl", "other-text"],
)
def test_other_lines_of_the_directory_model_are_not_noise(text: str) -> None:
    assert not is_known_noise(KDIRMODEL, None, text)


def test_an_ordinary_warning_is_not_noise() -> None:
    assert not is_known_noise("default", None, "QML Item: something else broke")


# -- the handler ---------------------------------------------------------------------------------


def test_the_handler_drops_the_known_lines_and_the_previous_handler_never_sees_them() -> None:
    seen: list[tuple[Any, ...]] = []
    handler = filtering_handler(lambda *args: seen.append(args))
    handler(0, context(file=KDE_MENU_ITEM), SHORTCUT_TEXT)
    handler(0, context(KDIRMODEL), removed(f"{TEMP_PREFIX}ab12cd"))
    assert seen == []


def test_the_previous_handler_gets_everything_else_unchanged() -> None:
    seen: list[tuple[Any, ...]] = []
    handler = filtering_handler(lambda *args: seen.append(args))
    ctx_other_file = context(file="qrc:/qt/qml/org/kde/desktop/Button.qml")
    ctx_other_folder = context(KDIRMODEL)
    ctx_plain = context()
    handler(1, ctx_other_file, SHORTCUT_TEXT)
    handler(1, ctx_other_folder, removed("Holiday"))
    handler(2, ctx_plain, "QML Item: something else broke")
    assert seen == [
        (1, ctx_other_file, SHORTCUT_TEXT),
        (1, ctx_other_folder, removed("Holiday")),
        (2, ctx_plain, "QML Item: something else broke"),
    ]
    assert seen[0][1] is ctx_other_file
