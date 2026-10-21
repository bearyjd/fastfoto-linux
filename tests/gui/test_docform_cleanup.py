"""The Documents form's paper cleanup choice: default off, checked, remembered, carried over."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents import CleanupPolicy
from fastfoto_linux.gui.docform import (
    DOCUMENT_CLEANUPS,
    DocumentForm,
    to_document_settings,
    update_document_field,
    validate_document_form,
)
from fastfoto_linux.gui.prefs import (
    PREFS_DIR,
    PREFS_FILE,
    load_document_form,
    save_document_form,
)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "config" / PREFS_DIR / PREFS_FILE


def test_the_default_is_off_and_the_choices_are_the_policy_values() -> None:
    assert DocumentForm().cleanup == "off"
    assert DOCUMENT_CLEANUPS == ("off", "light", "strong")


def test_a_choice_outside_the_presets_is_a_validation_error() -> None:
    assert validate_document_form(DocumentForm(cleanup="strong")) == {}
    assert set(validate_document_form(DocumentForm(cleanup="medium"))) == {"cleanup"}


def test_the_field_is_set_from_a_ui_value() -> None:
    assert update_document_field(DocumentForm(), "cleanup", "light").cleanup == "light"


@pytest.mark.parametrize("value", ["off", "light", "strong"])
def test_the_form_reaches_the_document_settings(value: str, tmp_path: Path) -> None:
    settings = to_document_settings(DocumentForm(cleanup=value), tmp_path, ocr_available=False)
    assert settings.cleanup is CleanupPolicy(value)


def test_the_setting_roundtrips_through_the_prefs(path: Path) -> None:
    form = replace(DocumentForm(), cleanup="strong")
    save_document_form(form, path)
    assert json.loads(path.read_text())["documents"]["cleanup"] == "strong"
    assert load_document_form(path) == form


def test_old_prefs_without_the_key_mean_off(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"documents": {"name": "Lease", "dpi": 150}}))
    assert load_document_form(path).cleanup == "off"


def test_a_bad_remembered_value_falls_back_to_off(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"documents": {"cleanup": "medium"}}))
    assert load_document_form(path).cleanup == "off"
