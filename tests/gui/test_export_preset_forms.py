"""The export preset of the Photos and Documents forms: allowlisted, forwarded, remembered."""

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.gui.docform import (
    DocumentForm,
    to_document_settings,
    update_document_field,
    validate_document_form,
)
from fastfoto_linux.gui.form import (
    ScanForm,
    destination,
    to_settings,
    update_field,
    validate_syntax,
)
from fastfoto_linux.gui.prefs import (
    PREFS_DIR,
    PREFS_FILE,
    load_document_form,
    load_form,
    save_document_form,
    save_form,
)
from fastfoto_linux.output.presets import ExportPreset

GOOD = [("high-quality", ExportPreset.HIGH_QUALITY), ("small", ExportPreset.SMALL)]
GOOD += [("lossless", ExportPreset.LOSSLESS)]
BAD = ["Small", " small", "small\n", "small\x00", "png", "secret/../x", True, 1, None, b"small"]
FIXED = "Choose Standard, High quality, Small or Lossless."


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "config" / PREFS_DIR / PREFS_FILE


@pytest.fixture
def form(out: Path) -> ScanForm:
    return ScanForm(output_folder=str(out))


def test_the_default_is_standard_and_changes_nothing(form: ScanForm) -> None:
    assert ScanForm().preset == "" and DocumentForm().preset == ""
    settings = to_settings(form)
    assert settings.preset is None and settings.quality is None
    docs = to_document_settings(DocumentForm(), Path("/x"), ocr_available=False)
    assert docs.preset is None


@pytest.mark.parametrize(("text", "preset"), GOOD)
def test_a_choice_reaches_both_settings(form: ScanForm, text: str, preset: ExportPreset) -> None:
    assert to_settings(replace(form, preset=text)).preset is preset
    docs = to_document_settings(DocumentForm(preset=text), Path("/x"), ocr_available=False)
    assert docs.preset is preset


@pytest.mark.parametrize("bad", BAD)
def test_update_refuses_anything_off_the_list_with_a_fixed_message(bad: object) -> None:
    for call in (
        lambda: update_field(ScanForm(), "preset", bad),
        lambda: update_document_field(DocumentForm(), "preset", bad),
    ):
        with pytest.raises(ValueError, match=FIXED) as caught:
            call()
        assert str(bad) not in str(caught.value) or str(bad) in FIXED


def test_update_accepts_the_list_and_standard() -> None:
    for text in ("", "lossless", "high-quality", "small"):
        assert update_field(ScanForm(), "preset", text).preset == text
        assert update_document_field(DocumentForm(), "preset", text).preset == text


@pytest.mark.parametrize("bad", BAD)
def test_validation_flags_a_bad_value_without_echoing_it(form: ScanForm, bad: object) -> None:
    errors = validate_syntax(replace(form, preset=bad))  # type: ignore[arg-type]
    assert errors == {"preset": FIXED}
    assert validate_document_form(DocumentForm(preset=bad)) == {"preset": FIXED}  # type: ignore[arg-type]


def test_validation_accepts_the_list(form: ScanForm) -> None:
    for text in ("", "lossless", "high-quality", "small"):
        assert "preset" not in validate_syntax(replace(form, preset=text))
        assert validate_document_form(DocumentForm(preset=text)) == {}


def test_the_name_preview_shows_png_only_for_lossless(form: ScanForm) -> None:
    assert destination(form).endswith("_####.jpg")  # type: ignore[union-attr]
    for text, ext in (("", ".jpg"), ("small", ".jpg"), ("high-quality", ".jpg")):
        assert destination(replace(form, preset=text)).endswith(f"_####{ext}")  # type: ignore[union-attr]
    assert destination(replace(form, preset="lossless")).endswith("_####.png")  # type: ignore[union-attr]


def test_the_preset_roundtrips_through_the_prefs(path: Path) -> None:
    save_form(ScanForm(preset="small"), path)
    assert load_form(path).preset == "small"
    save_document_form(DocumentForm(preset="lossless"), path)
    assert load_document_form(path).preset == "lossless"
    assert json.loads(path.read_text())["preset"] == "small"


def test_old_prefs_without_the_key_mean_standard(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"album": "A", "documents": {"name": "Lease"}}))
    assert load_form(path).preset == "" and load_document_form(path).preset == ""


BAD_PREFS = ["Small", " small", "small\n", "../x", True, 1, None, ["small"]]


@pytest.mark.parametrize("bad", BAD_PREFS)
def test_an_unknown_pref_value_falls_back_to_standard(
    path: Path, bad: object, caplog: pytest.LogCaptureFixture
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"preset": bad, "documents": {"preset": bad}}))
    with caplog.at_level(logging.WARNING):
        photos, docs = load_form(path), load_document_form(path)
    assert photos.preset == "" and docs.preset == ""
    assert validate_syntax(replace(photos, output_folder="/tmp")).get("preset") is None
