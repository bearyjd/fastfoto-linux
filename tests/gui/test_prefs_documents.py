"""Settings are remembered per mode, in the one file, and neither mode wipes the other."""

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.prefs import (
    PREFS_DIR,
    PREFS_FILE,
    load_document_form,
    load_form,
    load_mode,
    save_document_form,
    save_form,
    save_mode,
)
from fastfoto_linux.gui.state import Mode

LOGGER = "fastfoto_linux.gui.prefs"

CUSTOM = DocumentForm(
    name="Lease",
    colour="bw",
    dpi=600,
    both_sides=False,
    keep_blank=True,
    searchable=False,
    langs="eng+deu",
)
PHOTOS = ScanForm(output_folder="/srv/demo/FastFoto", album="Family Trips", dpi=300)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "config" / PREFS_DIR / PREFS_FILE


def written(path: Path) -> dict:
    return json.loads(path.read_text())


def test_a_saved_document_form_comes_back(path: Path) -> None:
    save_document_form(CUSTOM, path)
    assert load_document_form(path) == CUSTOM


def test_a_missing_file_gives_the_defaults_quietly(
    path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert load_document_form(path) == DocumentForm()
        assert load_mode(path) is Mode.PHOTOS
    assert caplog.records == []


def test_an_old_file_with_only_photo_settings_still_loads_in_both_ways(path: Path) -> None:
    save_form(PHOTOS, path)
    assert "documents" not in written(path)
    assert load_form(path) == PHOTOS
    assert load_document_form(path) == DocumentForm()
    assert load_mode(path) is Mode.PHOTOS


def test_saving_the_documents_keeps_the_photo_settings(path: Path) -> None:
    save_form(PHOTOS, path)
    save_document_form(CUSTOM, path)
    assert load_form(path) == PHOTOS
    assert load_document_form(path) == CUSTOM


def test_saving_the_photos_keeps_the_document_settings_and_the_mode(path: Path) -> None:
    save_document_form(CUSTOM, path)
    save_mode(Mode.DOCUMENTS, path)
    save_form(replace(PHOTOS, album="Rome"), path)
    assert load_document_form(path) == CUSTOM
    assert load_mode(path) is Mode.DOCUMENTS
    assert load_form(path).album == "Rome"


def test_the_output_folder_is_kept_once_for_both_modes(path: Path) -> None:
    save_form(PHOTOS, path)
    save_document_form(CUSTOM, path)
    saved = written(path)
    assert saved["output_folder"] == "/srv/demo/FastFoto"
    assert "output_folder" not in saved["documents"]


def test_the_mode_is_remembered(path: Path) -> None:
    save_mode(Mode.DOCUMENTS, path)
    assert load_mode(path) is Mode.DOCUMENTS
    save_mode(Mode.PHOTOS, path)
    assert load_mode(path) is Mode.PHOTOS


@pytest.mark.parametrize("bad", ["scans", 7, None, ["documents"]])
def test_a_mode_nobody_knows_is_photos(path: Path, bad: object) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mode": bad}))
    assert load_mode(path) is Mode.PHOTOS


def test_a_value_that_is_wrong_is_skipped_and_the_rest_is_kept(
    path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path.parent.mkdir(parents=True)
    documents = {"name": "Lease", "dpi": 150, "colour": "sepia", "langs": 7, "both_sides": "yes"}
    path.write_text(json.dumps({"documents": documents}))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        loaded = load_document_form(path)
    assert loaded == DocumentForm(name="Lease")
    assert len(caplog.records) == 4


def test_a_documents_entry_that_is_not_an_object_gives_the_defaults(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"documents": ["name"]}))
    assert load_document_form(path) == DocumentForm()


def test_a_file_that_is_not_json_gives_the_defaults_and_is_replaced_on_save(
    path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert load_document_form(path) == DocumentForm()
        assert load_mode(path) is Mode.PHOTOS
    save_document_form(CUSTOM, path)
    assert load_document_form(path) == CUSTOM


def test_what_a_newer_version_wrote_is_not_thrown_away(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"future": {"x": 1}, "documents": {"future_field": 2}}))
    save_document_form(CUSTOM, path)
    save_form(PHOTOS, path)
    save_mode(Mode.DOCUMENTS, path)
    assert written(path)["future"] == {"x": 1}


def test_a_save_leaves_no_temporary_file_behind(path: Path) -> None:
    save_document_form(CUSTOM, path)
    save_mode(Mode.DOCUMENTS, path)
    assert [entry.name for entry in path.parent.iterdir()] == [PREFS_FILE]


def test_a_save_that_fails_raises_oserror_and_keeps_the_old_file(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_document_form(CUSTOM, path)

    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", broken)
    with pytest.raises(OSError, match="disk full"):
        save_document_form(DocumentForm(name="Other"), path)
    monkeypatch.undo()
    assert load_document_form(path) == CUSTOM
    assert [entry.name for entry in path.parent.iterdir()] == [PREFS_FILE]
