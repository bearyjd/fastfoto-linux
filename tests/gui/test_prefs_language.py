"""The interface language preference: allowlisted, kept by the other saves."""

import json
import logging
from pathlib import Path

import pytest

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.prefs import (
    PREFS_DIR,
    PREFS_FILE,
    load_ui_language,
    save_form,
    save_ui_language,
)

LOGGER = "fastfoto_linux.gui.prefs"


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "config" / PREFS_DIR / PREFS_FILE


def test_english_when_nothing_is_saved(path: Path) -> None:
    assert load_ui_language(path) == "en"


def test_a_saved_language_is_read_back(path: Path) -> None:
    save_ui_language("de", path)
    assert load_ui_language(path) == "de"
    assert json.loads(path.read_text())["ui_language"] == "de"


@pytest.mark.parametrize("value", ["fr", "", "DE", "../de", 3, None, ["de"], {"de": 1}])
def test_a_bad_stored_value_is_english_and_logged(
    path: Path, value: object, caplog: pytest.LogCaptureFixture
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ui_language": value}))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert load_ui_language(path) == "en"
    if value is not None:
        assert "ui_language" in caplog.text


def test_a_broken_file_is_english(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert load_ui_language(path) == "en"


def test_saving_a_bad_language_is_refused_and_writes_nothing(path: Path) -> None:
    with pytest.raises(ValueError, match="language"):
        save_ui_language("fr", path)
    assert not path.exists()


def test_saving_the_language_keeps_the_rest_of_the_file(path: Path) -> None:
    save_form(ScanForm(album="Trips"), path)
    save_ui_language("de", path)
    data = json.loads(path.read_text())
    assert data["album"] == "Trips"
    assert data["ui_language"] == "de"


def test_saving_the_form_keeps_the_language(path: Path) -> None:
    save_ui_language("de", path)
    save_form(ScanForm(album="Trips"), path)
    assert load_ui_language(path) == "de"
