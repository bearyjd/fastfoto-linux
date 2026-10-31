"""Writing a document with a preset: draft bytes are re-read, and the sidecar does not change."""

from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft_store import REVIEW_FILE, THUMBS_DIR, save_draft
from fastfoto_linux.documents.errors import DocumentSettingsError
from fastfoto_linux.documents.settings import check_settings
from fastfoto_linux.documents.write import write_document
from fastfoto_linux.output.presets import ExportPreset
from tests.documents.store_helpers import raw_folder, store_settings


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def encoded_draft(tmp_path: Path, out: Path):
    folder, pages = raw_folder(tmp_path)
    settings = store_settings(out, keep_blank=True)
    return (
        folder,
        pages,
        settings,
        analyse_document(pages, settings, thumbs=folder / THUMBS_DIR, encode=True),
    )


def read_again(draft, settings) -> list[int]:
    seen: list[int] = []
    write_document(draft, settings, on_page=lambda number, total: seen.append(number))
    return seen


def test_without_a_preset_the_encoded_pages_are_reused(tmp_path: Path, out: Path) -> None:
    _, _, settings, draft = encoded_draft(tmp_path, out)

    assert read_again(draft, settings) == []


@pytest.mark.parametrize("preset", list(ExportPreset))
def test_with_a_preset_every_page_is_read_again(
    tmp_path: Path, out: Path, preset: ExportPreset
) -> None:
    _, _, settings, draft = encoded_draft(tmp_path, out)

    seen = read_again(draft, replace(settings, preset=preset))

    assert seen == list(range(1, len(draft.pages) + 1))


def test_the_sidecar_is_identical_with_and_without_a_preset(tmp_path: Path, out: Path) -> None:
    folder, _, settings, draft = encoded_draft(tmp_path, out)

    save_draft(draft, settings)
    plain = (folder / REVIEW_FILE).read_bytes()
    save_draft(draft, replace(settings, preset=ExportPreset.SMALL))

    assert (folder / REVIEW_FILE).read_bytes() == plain


@pytest.mark.parametrize("bad", ["small", 1, True])
def test_settings_refuse_a_preset_that_is_not_a_member(out: Path, bad: object) -> None:
    with pytest.raises(DocumentSettingsError, match="preset must be lossless"):
        check_settings(store_settings(out, preset=bad))
