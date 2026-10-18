"""``ffscan doc process`` with edits: --drop, --keep, --rotate, --split, --order, --part-name
and --dry-run."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from tests import _fake_ocrmypdf as fake
from tests.doc_synth import LEGAL_MM
from tests.documents.helpers import (
    blank_scene,
    page_size_pt,
    reader,
    text_scene,
    write_pages,
)

OFF = ["--ocr", "off", "--simplex"]


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


def doc(out: Path, pages: list[Path], *extra: str) -> int:
    return main(["doc", "process", *map(str, pages), "--out", str(out), *OFF, *extra])


def visible(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def sizes(pdf: Path) -> list[tuple[float, float]]:
    data = reader(pdf.read_bytes())
    return [page_size_pt(data, n) for n in range(len(data.pages))]


@pytest.fixture
def four(tmp_path: Path) -> list[Path]:
    scenes = [text_scene(1), blank_scene(2), text_scene(3), text_scene(4)]
    return write_pages(tmp_path / "raw", scenes)


def test_drop_removes_a_page_and_the_summary_says_so(four, out, capsys) -> None:
    assert doc(out, four, "--drop", "3") == 0
    lines = capsys.readouterr().out.splitlines()
    assert "pages read: 4" in lines
    assert "blank pages dropped: 1 (page 2)" in lines
    assert "pages removed: 1 (page 3)" in lines
    assert "pages in the PDF: 2" in lines
    assert len(reader((out / "Document_0001.pdf").read_bytes()).pages) == 2


def test_keep_brings_back_a_page_dropped_as_blank(four, out, capsys) -> None:
    assert doc(out, four, "--keep", "2") == 0
    lines = capsys.readouterr().out.splitlines()
    assert "blank pages dropped: 0" in lines
    assert "pages in the PDF: 4" in lines


def test_with_keep_blank_drop_still_wins(four, out) -> None:
    assert doc(out, four, "--keep-blank", "--drop", "2") == 0
    assert len(reader((out / "Document_0001.pdf").read_bytes()).pages) == 3


def test_rotate_turns_a_page_clockwise(four, out) -> None:
    assert doc(out, four, "--rotate", "1:90,3:180") == 0
    first, second, third = sizes(out / "Document_0001.pdf")
    plain = sizes_of_plain(out, four)
    assert first == pytest.approx(tuple(reversed(plain[0])), abs=0.5)
    assert second == pytest.approx(plain[1], abs=0.5)
    assert third == pytest.approx(plain[2], abs=0.5)


def sizes_of_plain(out: Path, pages: list[Path]) -> list[tuple[float, float]]:
    other = out.parent / "plain"
    other.mkdir()
    assert main(["doc", "process", *map(str, pages), "--out", str(other), *OFF]) == 0
    return sizes(other / "Document_0001.pdf")


def test_order_puts_the_pages_in_the_order_given(tmp_path, out) -> None:
    scenes = [text_scene(1), text_scene(2, paper_mm=LEGAL_MM), text_scene(3)]
    pages = write_pages(tmp_path / "raw", scenes)
    assert doc(out, pages, "--order", "2,1,3") == 0
    heights = [height for _, height in sizes(out / "Document_0001.pdf")]
    assert heights[0] > heights[1]
    assert heights[1] == pytest.approx(heights[2], abs=0.5)


def test_split_makes_one_pdf_per_part_and_the_summary_lists_each(four, out, capsys) -> None:
    assert doc(out, four, "--split", "4") == 0
    assert visible(out) == ["Document (part 1)_0001.pdf", "Document (part 2)_0001.pdf"]
    lines = capsys.readouterr().out.splitlines()
    assert "pages in the PDFs: 3" in lines
    assert f"file written: {out / 'Document (part 1)_0001.pdf'} (2 pages)" in lines
    assert f"file written: {out / 'Document (part 2)_0001.pdf'} (1 page)" in lines


def test_part_name_names_each_pdf(four, out) -> None:
    assert doc(out, four, "--split", "4", "--part-name", "1=Tax return,2=Receipts") == 0
    assert visible(out) == ["Receipts_0001.pdf", "Tax return_0001.pdf"]
    title = reader((out / "Receipts_0001.pdf").read_bytes()).metadata.title
    assert title == "Receipts"


def test_part_names_are_cleaned_like_album_names(four, out) -> None:
    assert doc(out, four, "--part-name", "1=My/Taxes") == 0
    assert visible(out) == ["My Taxes_0001.pdf"]


def test_dropping_every_page_is_an_error_that_writes_nothing(four, out, capsys) -> None:
    assert doc(out, four, "--drop", "1,3,4") == 1
    assert "no page is left" in capsys.readouterr().err
    assert visible(out) == []


# ---- --dry-run --------------------------------------------------------------------------------


def _row(output: str, number: int) -> list[str]:
    rows = [line.split() for line in output.splitlines() if line.split()[:1] == [str(number)]]
    assert len(rows) == 1, output
    return rows[0]


def test_dry_run_prints_a_table_and_writes_nothing(four, out, capsys) -> None:
    assert doc(out, four, "--dry-run") == 0
    text = capsys.readouterr().out
    assert text.splitlines()[0].split()[:4] == ["page", "verdict", "flags", "part"]
    assert _row(text, 1)[1:2] == ["kept"]
    assert _row(text, 2)[1] == "blank"
    assert "left out" in " ".join(_row(text, 2))
    assert _row(text, 2)[3] == "-"
    assert visible(out) == []
    assert not any(p.name.endswith(".tmp") for p in out.iterdir())


def test_dry_run_shows_what_the_edits_do(four, out, capsys) -> None:
    edits = ["--drop", "3", "--keep", "2", "--rotate", "1:270", "--split", "4"]
    assert doc(out, four, "--dry-run", *edits) == 0
    text = capsys.readouterr().out
    assert "turned 270" in " ".join(_row(text, 1))
    assert "brought back" in " ".join(_row(text, 2))
    assert "removed" in " ".join(_row(text, 3))
    assert _row(text, 3)[3] == "-"
    assert _row(text, 4)[3] == "2"
    assert "starts a new PDF" in " ".join(_row(text, 4))
    assert visible(out) == []


def test_dry_run_says_when_no_pdf_would_be_written(four, out, capsys) -> None:
    assert doc(out, four, "--dry-run", "--drop", "1,3,4") == 0
    assert "no PDF would be written" in capsys.readouterr().out
    assert visible(out) == []


def test_doc_scan_has_no_edit_options(out) -> None:
    assert main(["doc", "scan", "--out", str(out), "--drop", "1"]) == 2
