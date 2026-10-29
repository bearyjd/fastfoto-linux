"""The Documents form's "Straighten tilted pages" switch: default off, strict, remembered."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.gui.docform import (
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


def test_the_default_is_off() -> None:
    assert DocumentForm().deskew is False


@pytest.mark.parametrize("bad", ["yes", "false", 1, None])
def test_a_value_that_is_not_a_bool_is_a_validation_error(bad: object) -> None:
    assert validate_document_form(DocumentForm(deskew=True)) == {}
    assert set(validate_document_form(DocumentForm(deskew=bad))) == {"deskew"}  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False])
def test_the_field_is_set_from_a_ui_switch(value: bool) -> None:
    assert update_document_field(DocumentForm(), "deskew", value).deskew is value


@pytest.mark.parametrize("value", ["false", "", 0, 1, None])
def test_a_ui_value_that_is_not_a_bool_is_refused_not_coerced(value: object) -> None:
    with pytest.raises(ValueError):
        update_document_field(DocumentForm(), "deskew", value)


@pytest.mark.parametrize("value", [True, False])
def test_the_form_reaches_the_document_settings(value: bool, tmp_path: Path) -> None:
    settings = to_document_settings(DocumentForm(deskew=value), tmp_path, ocr_available=False)
    assert settings.deskew is value


def test_the_setting_roundtrips_through_the_prefs(path: Path) -> None:
    form = replace(DocumentForm(), deskew=True)
    save_document_form(form, path)
    assert json.loads(path.read_text())["documents"]["deskew"] is True
    assert load_document_form(path) == form


def test_old_prefs_without_the_key_mean_off(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"documents": {"name": "Lease", "despeckle": True}}))
    assert load_document_form(path).deskew is False


@pytest.mark.parametrize("bad", ["yes", 1, None])
def test_a_remembered_value_that_is_not_a_bool_falls_back_to_off(path: Path, bad: object) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"documents": {"deskew": bad}}))
    assert load_document_form(path).deskew is False
