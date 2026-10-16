"""The Documents form: checked field by field, turned into a document scan request."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import DEFAULT_NAME, ColourMode, OcrMode
from fastfoto_linux.gui.docform import (
    DOCUMENT_COLOURS,
    DocumentForm,
    document_destination,
    document_errors,
    ocr_mode,
    to_document_request,
    to_document_settings,
    update_document_field,
    validate_document_form,
)
from fastfoto_linux.gui.form import FormInvalidError
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import DOCUMENT_DPI, RawPolicy
from tests.cli.fakes import DEVICE

TARGET = ScanTarget(device=DEVICE)


def test_the_defaults_are_those_of_ffscan_doc_scan() -> None:
    form = DocumentForm()
    assert (form.name, form.colour, form.dpi) == ("", "colour", 300)
    assert (form.both_sides, form.keep_blank, form.searchable, form.langs) == (
        True,
        False,
        True,
        "eng",
    )


def test_the_colour_choices_are_the_cli_ones() -> None:
    assert DOCUMENT_COLOURS == ("colour", "grey", "bw")
    assert tuple(mode.value for mode in ColourMode) == DOCUMENT_COLOURS


def test_the_default_form_is_valid() -> None:
    assert validate_document_form(DocumentForm()) == {}


@pytest.mark.parametrize("name", ["", "   ", "Tax 2026", "Lease (signed)"])
def test_a_blank_name_means_the_default_and_a_usable_one_is_fine(name: str) -> None:
    assert "name" not in validate_document_form(DocumentForm(name=name))


@pytest.mark.parametrize("name", ["///", "..", "   /   "])
def test_a_name_with_no_usable_characters_is_refused_in_plain_words(name: str) -> None:
    message = validate_document_form(DocumentForm(name=name))["name"]
    assert "file name" in message


@pytest.mark.parametrize("langs", ["eng", "eng+deu", "chi_sim"])
def test_tesseract_language_codes_are_accepted(langs: str) -> None:
    assert "langs" not in validate_document_form(DocumentForm(langs=langs))


@pytest.mark.parametrize("langs", ["", "eng;rm", "eng deu", "$(x)", "eng+"])
def test_anything_else_is_refused_with_the_rule_the_command_line_has(langs: str) -> None:
    assert "Tesseract" in validate_document_form(DocumentForm(langs=langs))["langs"]


def test_a_colour_that_is_not_offered_is_refused() -> None:
    assert "colour" in validate_document_form(DocumentForm(colour="sepia"))


@pytest.mark.parametrize("dpi", DOCUMENT_DPI)
def test_the_document_resolutions_are_accepted(dpi: int) -> None:
    assert "dpi" not in validate_document_form(DocumentForm(dpi=dpi))


@pytest.mark.parametrize("dpi", [150, 1200, 0])
def test_a_resolution_that_is_not_for_documents_is_refused(dpi: int) -> None:
    assert "dpi" in validate_document_form(DocumentForm(dpi=dpi))


def test_every_bad_field_has_its_own_message() -> None:
    errors = validate_document_form(DocumentForm(name="///", colour="x", dpi=7, langs="!"))
    assert set(errors) == {"name", "colour", "dpi", "langs"}


# -- editing ---------------------------------------------------------------------------------


def test_a_field_is_set_on_a_copy() -> None:
    form = DocumentForm()
    changed = update_document_field(form, "name", "Lease")
    assert (changed.name, form.name) == ("Lease", "")


@pytest.mark.parametrize("name", ["both_sides", "keep_blank", "searchable"])
def test_switches_take_a_truth_value(name: str) -> None:
    assert getattr(update_document_field(DocumentForm(), name, False), name) is False
    assert getattr(update_document_field(DocumentForm(), name, True), name) is True


@pytest.mark.parametrize("value", [200, 200.0, "200"])
def test_the_resolution_takes_a_number_from_the_ui(value: object) -> None:
    assert update_document_field(DocumentForm(), "dpi", value).dpi == 200


@pytest.mark.parametrize("value", [200.5, "fast", None])
def test_a_resolution_that_is_not_a_whole_number_is_an_error(value: object) -> None:
    with pytest.raises(ValueError, match="whole number"):
        update_document_field(DocumentForm(), "dpi", value)


def test_a_field_the_form_does_not_have_is_an_error() -> None:
    with pytest.raises(ValueError, match="no field"):
        update_document_field(DocumentForm(), "album", "x")


# -- searchable text -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("searchable", "available", "expected"),
    [
        (True, True, OcrMode.ON),
        (False, True, OcrMode.OFF),
        (True, False, OcrMode.OFF),
        (False, False, OcrMode.OFF),
    ],
)
def test_searchable_text_is_asked_for_only_when_wanted_and_installed(
    searchable: bool, available: bool, expected: OcrMode
) -> None:
    form = DocumentForm(searchable=searchable)
    assert ocr_mode(form, ocr_available=available) is expected


# -- the settings and the request ------------------------------------------------------------


def test_the_settings_follow_the_form(tmp_path: Path) -> None:
    form = DocumentForm(
        name=" Lease ", colour="bw", keep_blank=True, langs="eng+deu", searchable=True
    )
    settings = to_document_settings(form, tmp_path, ocr_available=True)
    assert settings.output_root == tmp_path
    assert settings.name == "Lease"
    assert settings.colour is ColourMode.BW
    assert settings.keep_blank is True
    assert settings.langs == "eng+deu"
    assert settings.ocr is OcrMode.ON


def test_a_blank_name_is_the_default_name(tmp_path: Path) -> None:
    assert to_document_settings(DocumentForm(), tmp_path, ocr_available=False).name == DEFAULT_NAME


def test_the_request_scans_both_sides_unless_told_otherwise(tmp_path: Path) -> None:
    duplex = to_document_request(DocumentForm(), str(tmp_path), TARGET, ocr_available=False)
    simplex = to_document_request(
        DocumentForm(both_sides=False, dpi=600), str(tmp_path), TARGET, ocr_available=False
    )
    assert (duplex.duplex, duplex.dpi, duplex.raw_policy) == (True, 300, RawPolicy.AUTO)
    assert (simplex.duplex, simplex.dpi) == (False, 600)
    assert duplex.target == TARGET
    assert duplex.settings.output_root == tmp_path


def test_a_tilde_in_the_folder_is_the_home_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Docs").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    request = to_document_request(DocumentForm(), "~/Docs", TARGET, ocr_available=False)
    assert request.settings.output_root == tmp_path / "Docs"


def test_a_bad_form_is_refused_with_a_message_per_field(tmp_path: Path) -> None:
    with pytest.raises(FormInvalidError) as refused:
        to_document_request(DocumentForm(name="///"), str(tmp_path), TARGET, ocr_available=False)
    assert set(refused.value.errors) == {"name"}


@pytest.mark.parametrize("folder", ["", "relative/dir"])
def test_a_folder_that_is_not_a_full_path_is_refused(folder: str) -> None:
    with pytest.raises(FormInvalidError) as refused:
        to_document_request(DocumentForm(), folder, TARGET, ocr_available=False)
    assert set(refused.value.errors) == {"output_folder"}


def test_a_folder_that_is_missing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FormInvalidError) as refused:
        to_document_request(DocumentForm(), str(tmp_path / "gone"), TARGET, ocr_available=False)
    assert "does not exist" in refused.value.errors["output_folder"]


# -- errors for the page ---------------------------------------------------------------------


def test_the_folder_text_is_checked_without_the_disk_and_with_it(tmp_path: Path) -> None:
    gone = str(tmp_path / "gone")
    assert document_errors(DocumentForm(), gone, disk=False) == {}
    assert "does not exist" in document_errors(DocumentForm(), gone, disk=True)["output_folder"]
    assert "full path" in document_errors(DocumentForm(), "rel", disk=False)["output_folder"]


def test_the_folder_comes_first_then_the_fields_in_form_order(tmp_path: Path) -> None:
    errors = document_errors(DocumentForm(name="///", langs="!"), "rel", disk=False)
    assert list(errors) == ["output_folder", "name", "langs"]


def test_nothing_about_photos_is_checked_for_documents(tmp_path: Path) -> None:
    assert document_errors(DocumentForm(), str(tmp_path), disk=True) == {}


# -- where the PDF will go -------------------------------------------------------------------


def test_the_destination_shows_the_folder_and_the_name_with_a_number_to_come(
    tmp_path: Path,
) -> None:
    assert document_destination(DocumentForm(), str(tmp_path)) == f"{tmp_path}/Document_####.pdf"
    named = document_destination(DocumentForm(name="Tax 2026"), str(tmp_path))
    assert named is not None
    assert named.startswith(f"{tmp_path}/Tax") and named.endswith("_####.pdf")


@pytest.mark.parametrize(("name", "folder"), [("///", "/tmp"), ("Lease", ""), ("Lease", "rel")])
def test_the_destination_is_unknown_while_the_name_or_the_folder_is_bad(
    name: str, folder: str
) -> None:
    assert document_destination(DocumentForm(name=name), folder) is None
