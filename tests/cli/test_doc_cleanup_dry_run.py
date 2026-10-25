"""``doc process --dry-run`` says which paper cleanup level each kept page gets, and which pages
are cropped, and says nothing new when there is neither."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.documents.draft_edit import set_cleanup, set_crop, set_document_cleanup
from fastfoto_linux.documents.draft_store import save_draft
from fastfoto_linux.documents.modes import CleanupPolicy
from fastfoto_linux.documents.page_crop import PageCrop
from tests.cli.doc_cleanup_helpers import LIGHT, OCR_OFF, STRONG, raw_folder_of, shaded_pages
from tests.documents.store_helpers import analysed, raw_folder, store_settings

pytestmark = pytest.mark.usefixtures("no_real_ocr")

CROP = PageCrop(1000, 2000, 7000, 9000)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


def dry_run(capsys: pytest.CaptureFixture[str], out: Path, source: list[Path], *extra: str) -> str:
    argv = ["doc", "process", *map(str, source), "--out", str(out), *OCR_OFF, "--dry-run", *extra]
    assert main(argv) == 0
    assert list(out.iterdir()) == []
    return capsys.readouterr().out


def row(text: str, number: int) -> str:
    rows = [line for line in text.splitlines() if line.split()[:1] == [str(number)]]
    assert len(rows) == 1, text
    return " ".join(rows[0].split())


def stored(tmp_path: Path, out: Path, level: CleanupPolicy) -> Path:
    """A raw folder of two pages with the document level, an override of page 2, a crop of 1."""
    folder, pages = raw_folder_of(tmp_path, count=2)
    settings = store_settings(out, duplex=False)
    draft = set_document_cleanup(analysed(folder, pages, settings), level)
    save_draft(set_crop(set_cleanup(draft, 2, STRONG), 1, CROP), settings)
    return folder


def test_each_kept_page_shows_its_level_an_override_and_a_crop(tmp_path, out, capsys) -> None:
    folder = stored(tmp_path, out, LIGHT)
    text = dry_run(capsys, out, [folder])
    first, second = row(text, 1), row(text, 2)
    assert "cropped" in first
    assert first.endswith("; cleanup=light")
    assert second.endswith("; cleanup=strong override")
    assert "cropped" not in second


def test_the_flag_changes_the_document_level_and_not_the_override(tmp_path, out, capsys) -> None:
    folder = stored(tmp_path, out, LIGHT)
    text = dry_run(capsys, out, [folder], "--cleanup", "off")
    assert row(text, 1).endswith("; cleanup=off")
    assert row(text, 2).endswith("; cleanup=strong override")


def test_a_black_and_white_page_shows_cleanup_off(tmp_path, out, capsys) -> None:
    pages = shaded_pages(tmp_path / "raw")
    text = dry_run(capsys, out, pages, "--cleanup", "strong", "--colour", "bw")
    assert row(text, 1).endswith("; cleanup=off")
    text = dry_run(capsys, out, pages, "--cleanup", "strong", "--colour", "grey")
    assert row(text, 1).endswith("; cleanup=strong")


def test_the_level_is_shown_after_the_colour_reason(tmp_path, out, capsys) -> None:
    pages = shaded_pages(tmp_path / "raw")
    text = dry_run(capsys, out, pages, "--cleanup", "light", "--colour", "auto")
    assert "; colour=" in row(text, 1)
    assert row(text, 1).endswith("; cleanup=light")


def test_an_override_on_one_page_shows_off_on_the_others(tmp_path, out, capsys) -> None:
    folder, pages = raw_folder_of(tmp_path, count=2)
    settings = store_settings(out, duplex=False)
    save_draft(set_cleanup(analysed(folder, pages, settings), 2, STRONG), settings)
    text = dry_run(capsys, out, [folder])
    assert row(text, 1).endswith("; cleanup=off")
    assert row(text, 2).endswith("; cleanup=strong override")


def test_without_cleanup_or_a_crop_the_table_has_neither_word(tmp_path, out, capsys) -> None:
    folder, _pages = raw_folder_of(tmp_path, count=2)
    text = dry_run(capsys, out, [folder])
    assert "cleanup" not in text
    assert "cropped" not in text
    assert "override" not in text


def test_a_page_that_is_left_out_has_no_cleanup_word(tmp_path, out, capsys) -> None:
    folder, pages = raw_folder(tmp_path)
    settings = store_settings(out, duplex=False)
    save_draft(set_document_cleanup(analysed(folder, pages, settings), LIGHT), settings)
    text = dry_run(capsys, out, [folder])
    assert "left out (looks blank)" in row(text, 2)
    assert "cleanup" not in row(text, 2)
    assert row(text, 1).endswith("; cleanup=light")
