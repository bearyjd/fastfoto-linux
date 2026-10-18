"""``ffscan doc process RAWDIR``: a raw folder as the input, with the edits of its ``review.json``
under the command-line edits. The command never writes the sidecar."""

import logging
import os
from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.documents import draft_store
from fastfoto_linux.documents.draft_edit import rotate, set_included
from fastfoto_linux.documents.draft_store import REVIEW_FILE, save_draft
from tests import _fake_ocrmypdf as fake
from tests.documents.helpers import page_size_pt, reader
from tests.documents.store_helpers import analysed, raw_folder, store_settings

OFF = ["--ocr", "off", "--simplex"]


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.fixture
def raw(tmp_path: Path, out: Path) -> Path:
    return raw_folder(tmp_path)[0]


def process(out: Path, folder: Path, *extra: str) -> int:
    return main(["doc", "process", str(folder), "--out", str(out), *OFF, *extra])


def pdf_pages(out: Path, name: str = "Document_0001.pdf") -> list[tuple[float, float]]:
    data = reader((out / name).read_bytes())
    return [page_size_pt(data, n) for n in range(len(data.pages))]


def save_edited(raw: Path, out: Path) -> None:
    """A sidecar that removes page 3 and turns page 1 a quarter turn."""
    pages = sorted(raw.glob("page-*.png"))
    settings = store_settings(out, duplex=False)
    draft = rotate(set_included(analysed(raw, tuple(pages), settings), 3, False), 1, 1)
    save_draft(draft, settings)


def listing(folder: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(folder)), p.stat().st_mtime_ns) for p in folder.rglob("*"))


def test_a_folder_without_a_sidecar_is_processed_as_its_pages_would_be(raw, out, capsys) -> None:
    assert process(out, raw) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "pages read: 4" in lines
    assert "blank pages dropped: 1 (page 2)" in lines
    assert len(pdf_pages(out)) == 3


def test_the_edits_of_the_sidecar_are_applied(raw, out, capsys) -> None:
    save_edited(raw, out)
    assert process(out, raw) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "pages removed: 1 (page 3)" in lines
    sizes = pdf_pages(out)
    assert len(sizes) == 2
    assert sizes[0] != sizes[1]  # page 1 was turned, page 4 was not


def test_fresh_ignores_the_sidecar(raw, out) -> None:
    save_edited(raw, out)
    assert process(out, raw, "--fresh") == 0
    assert len(pdf_pages(out)) == 3


def test_command_line_edits_come_on_top_of_the_sidecar(raw, out, capsys) -> None:
    save_edited(raw, out)
    assert process(out, raw, "--keep", "3", "--drop", "4") == 0
    lines = capsys.readouterr().out.splitlines()
    assert "pages removed: 1 (page 4)" in lines
    assert len(pdf_pages(out)) == 2


def test_the_command_never_writes_the_sidecar(raw, out) -> None:
    before = listing(raw)
    assert process(out, raw) == 0
    assert listing(raw) == before
    assert not (raw / REVIEW_FILE).exists()
    assert not (raw / "thumbs").exists()


def test_the_command_leaves_an_existing_sidecar_alone(raw, out) -> None:
    save_edited(raw, out)
    before = listing(raw)
    content = (raw / REVIEW_FILE).read_bytes()
    assert process(out, raw, "--drop", "1") == 0
    assert listing(raw) == before
    assert (raw / REVIEW_FILE).read_bytes() == content


def test_a_fresh_sidecar_saves_the_analysis(raw, out, monkeypatch: pytest.MonkeyPatch) -> None:
    save_edited(raw, out)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("analysed again")

    monkeypatch.setattr(draft_store, "analyse_document", refuse)
    assert process(out, raw) == 0
    assert len(pdf_pages(out)) == 2


def test_a_tampered_sidecar_is_ignored_with_a_warning(raw, out, caplog) -> None:
    (raw / REVIEW_FILE).write_text('{"version": 1, "pages": "../../etc"}', encoding="utf-8")
    caplog.set_level(logging.WARNING)
    assert process(out, raw) == 0
    assert len(pdf_pages(out)) == 3
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_dry_run_reads_the_folder_and_writes_nothing(raw, out, capsys) -> None:
    save_edited(raw, out)
    assert process(out, raw, "--dry-run") == 0
    printed = capsys.readouterr().out
    assert "left out (you removed it)" in printed
    assert not list(out.glob("*.pdf"))


def test_a_folder_with_no_pages_is_a_usage_error(tmp_path, out, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert process(out, empty) == 2
    assert "no page" in capsys.readouterr().err
    assert not list(out.glob("*.pdf"))


def test_a_number_beyond_the_folders_pages_is_a_usage_error(raw, out, capsys) -> None:
    assert process(out, raw, "--drop", "9") == 2
    assert "page 9" in capsys.readouterr().err


def test_a_folder_among_files_is_a_usage_error(raw, out, capsys) -> None:
    page = sorted(raw.glob("page-*.png"))[0]
    assert main(["doc", "process", str(raw), str(page), "--out", str(out), *OFF]) == 2
    assert "folder" in capsys.readouterr().err


def test_fresh_needs_a_folder(raw, out, capsys) -> None:
    pages = [str(p) for p in sorted(raw.glob("page-*.png"))]
    assert main(["doc", "process", *pages, "--out", str(out), *OFF, "--fresh"]) == 2
    assert "--fresh" in capsys.readouterr().err
    assert not os.listdir(out)
