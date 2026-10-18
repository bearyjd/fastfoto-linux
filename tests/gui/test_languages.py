"""Picker selections remain CLI-compatible, readable, and usable offline."""

import pytest

from fastfoto_linux.documents.ocr_languages import Inventory, Language
from fastfoto_linux.gui.languages import (
    download_codes,
    language_rows,
    language_summary,
    missing_languages,
    toggle_language,
)


@pytest.fixture
def inventory() -> Inventory:
    return Inventory(
        (
            Language("eng", "English", 100, installed=True),
            Language("spa", "Spanish", 200),
            Language("deu", "German", 300),
            Language("custom", "custom", 0, installed=True),
        )
    )


def test_selection_preserves_saved_order_and_custom_codes() -> None:
    assert toggle_language("spa+custom+eng", "deu", True) == "spa+custom+eng+deu"
    assert toggle_language("spa+custom+eng", "custom", False) == "spa+eng"
    assert toggle_language("spa+custom+eng", "eng", True) == "spa+custom+eng"


def test_last_checkbox_can_be_cleared_without_silently_selecting_english() -> None:
    assert toggle_language("eng", "eng", False) == ""
    assert toggle_language("", "spa", True) == "spa"


def test_picker_lists_readable_names_codes_and_download_status(inventory: Inventory) -> None:
    rows = language_rows(inventory, "spa+custom")
    spanish = next(row for row in rows if row["code"] == "spa")
    assert spanish["name"] == "Spanish"
    assert spanish["selected"] is True
    assert spanish["installed"] is False
    assert "Download required" in spanish["status"]
    assert "200" in spanish["status"]
    english = next(row for row in rows if row["code"] == "eng")
    assert english["status"] == "Installed"
    assert english["selected"] is False


@pytest.mark.parametrize("search", ["SPAN", "sPa", "Spanish"])
def test_search_matches_names_and_codes_without_changing_selection(
    inventory: Inventory, search: str
) -> None:
    assert [row["code"] for row in language_rows(inventory, "eng+custom", search)] == ["spa"]


def test_summary_and_missing_follow_selected_order(inventory: Inventory) -> None:
    summary = language_summary(inventory, "spa+custom+eng")
    assert summary.index("Spanish") < summary.index("custom") < summary.index("English")
    assert missing_languages(inventory, "spa+custom+eng") == ("spa",)
    assert missing_languages(inventory, "unknown+spa") == ("unknown", "spa")


def test_unknown_saved_codes_stay_visible_instead_of_disappearing(inventory: Inventory) -> None:
    rows = language_rows(inventory, "unknown+eng")
    unknown = next(row for row in rows if row["code"] == "unknown")
    assert unknown["selected"] is True
    assert "Unavailable" in unknown["status"]


def test_empty_selection_has_a_clear_summary(inventory: Inventory) -> None:
    assert language_summary(inventory, "") == "Choose at least one text language."


def test_orientation_is_included_only_when_needed(inventory: Inventory) -> None:
    missing_osd = Inventory(inventory.languages, orientation=Language("osd", "Orientation", 400))
    assert download_codes(missing_osd, "eng+spa") == ("spa", "osd")
    assert missing_languages(missing_osd, "eng") == ("osd",)
    installed_osd = Inventory(
        inventory.languages, orientation=Language("osd", "Orientation", 400, installed=True)
    )
    assert download_codes(installed_osd, "eng") == ()
    assert download_codes(missing_osd, "") == ()
