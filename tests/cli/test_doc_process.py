"""``ffscan doc process``: page files in, one PDF out."""

import hashlib
from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from tests import _fake_ocrmypdf as fake
from tests.doc_synth import LEGAL_MM, write_png
from tests.documents.helpers import (
    blank_scene,
    image_object,
    page_size_pt,
    reader,
    text_scene,
    write_pages,
)

OFF = ["--ocr", "off"]


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


def doc(out: Path, pages, *extra: str) -> int:
    return main(["doc", "process", *map(str, pages), "--out", str(out), *OFF, *extra])


def visible(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def test_pages_become_one_pdf_and_the_summary_says_what_happened(tmp_path, out, capsys) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1), blank_scene(2), text_scene(3)])
    assert doc(out, pages) == 0
    assert visible(out) == ["Document_0001.pdf"]
    assert len(reader((out / "Document_0001.pdf").read_bytes()).pages) == 2
    lines = capsys.readouterr().out.splitlines()
    assert "pages read: 3" in lines
    assert "blank pages dropped: 1 (page 2)" in lines
    assert "pages in the PDF: 2" in lines
    assert any(line.startswith("searchable text: no") for line in lines)
    assert f"file written: {out / 'Document_0001.pdf'}" in lines
    assert any(line.startswith("raw pages:") for line in lines)


def test_several_dropped_pages_are_listed_by_number(tmp_path, out, capsys) -> None:
    pages = write_pages(
        tmp_path / "raw", [text_scene(1), blank_scene(2), text_scene(3), blank_scene(4)]
    )
    assert doc(out, pages) == 0
    assert "blank pages dropped: 2 (pages 2, 4)" in capsys.readouterr().out.splitlines()


def test_keep_blank_keeps_every_page(tmp_path, out, capsys) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1), blank_scene(2)])
    assert doc(out, pages, "--keep-blank") == 0
    assert len(reader((out / "Document_0001.pdf").read_bytes()).pages) == 2
    assert "blank pages dropped: 0" in capsys.readouterr().out.splitlines()


def test_pages_are_taken_in_natural_filename_order(tmp_path, out) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    letter = write_pages(raw / "a", [text_scene(1)])[0]
    legal = write_pages(raw / "b", [text_scene(2, paper_mm=LEGAL_MM)])[0]
    second = letter.rename(raw / "page-2.png")
    tenth = legal.rename(raw / "page-10.png")
    assert doc(out, [tenth, second]) == 0  # given backwards
    pdf = reader((out / "Document_0001.pdf").read_bytes())
    assert page_size_pt(pdf, 0)[1] == pytest.approx(792, abs=1)
    assert page_size_pt(pdf, 1)[1] == pytest.approx(1008, abs=1)


def test_the_name_option_names_the_file(tmp_path, out) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1)])
    assert doc(out, pages, "--name", "Tax Return 2025") == 0
    assert visible(out) == ["Tax Return 2025_0001.pdf"]


def test_numbers_are_shared_with_photos_and_never_reused(tmp_path, out) -> None:
    (out / "FastFoto_0007.jpg").write_bytes(b"photo")
    pages = write_pages(tmp_path / "raw", [text_scene(1)])
    assert doc(out, pages, "--name", "FastFoto") == 0
    assert doc(out, pages, "--name", "FastFoto") == 0
    assert visible(out) == ["FastFoto_0007.jpg", "FastFoto_0008.pdf", "FastFoto_0009.pdf"]


def test_an_earlier_pdf_is_never_overwritten(tmp_path, out) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1)])
    assert doc(out, pages) == 0
    first = (out / "Document_0001.pdf").read_bytes()
    assert doc(out, pages) == 0
    assert (out / "Document_0001.pdf").read_bytes() == first
    assert visible(out) == ["Document_0001.pdf", "Document_0002.pdf"]


def test_input_pages_are_never_deleted_or_changed(tmp_path, out) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1), blank_scene(2)])
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in pages}
    assert doc(out, pages) == 0
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in pages} == before


@pytest.mark.parametrize(
    ("colour", "codec"),
    [("colour", "/DCTDecode"), ("grey", "/DCTDecode"), ("bw", ["/CCITTFaxDecode"])],
)
def test_the_colour_option_chooses_how_pages_are_stored(tmp_path, out, colour, codec) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1)])
    assert doc(out, pages, "--colour", colour) == 0
    image = image_object(reader((out / "Document_0001.pdf").read_bytes()), 0)
    assert image["/Filter"] == codec
    assert image["/ColorSpace"] == ("/DeviceRGB" if colour == "colour" else "/DeviceGray")


def test_the_dpi_option_is_only_a_fallback_for_pages_without_a_resolution(
    tmp_path, out, capsys
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    bare = write_png(raw / "bare.png", text_scene(1).image, dpi=None)
    assert doc(out, [bare]) == 1
    assert "resolution" in capsys.readouterr().err
    assert visible(out) == []
    assert doc(out, [bare], "--dpi", "100") == 0
    page = reader((out / "Document_0001.pdf").read_bytes())
    assert page_size_pt(page, 0)[0] == pytest.approx(612, abs=1)
    other = write_pages(tmp_path / "set", [text_scene(2)])
    assert doc(out, other, "--dpi", "600") == 0  # the file says 100 and wins
    assert page_size_pt(reader((out / "Document_0002.pdf").read_bytes()), 0)[0] == pytest.approx(
        612, abs=1
    )


def test_when_every_page_is_blank_nothing_is_written_and_the_hint_names_keep_blank(
    tmp_path, out, capsys
) -> None:
    pages = write_pages(tmp_path / "raw", [blank_scene(1), blank_scene(2)])
    assert doc(out, pages) == 1
    assert visible(out) == []
    assert "--keep-blank" in capsys.readouterr().err
    assert all(p.exists() for p in pages)


def test_an_unusable_page_is_exit_1_with_its_name_and_nothing_is_written(
    tmp_path, out, capsys
) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1), text_scene(2)])
    pages[1].write_bytes(b"not a png")
    assert doc(out, pages) == 1
    err = capsys.readouterr().err
    assert "page-02.png" in err
    assert "Traceback" not in err
    assert visible(out) == []


# ---- usage errors ---------------------------------------------------------------------------


def test_a_missing_page_file_is_a_usage_error(tmp_path, out, capsys) -> None:
    assert doc(out, [tmp_path / "nope.png"]) == 2
    assert "nope.png" in capsys.readouterr().err


def test_a_missing_output_folder_needs_mkdir(tmp_path) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1)])
    target = tmp_path / "new" / "pdfs"
    assert doc(target, pages) == 2
    assert not target.exists()
    assert doc(target, pages, "--mkdir") == 0
    assert visible(target) == ["Document_0001.pdf"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["doc"],
        ["doc", "process"],
        ["doc", "process", "x.png"],  # no --out
        ["doc", "process", "x.png", "--out", "o", "--lang", "ENG"],
        ["doc", "process", "x.png", "--out", "o", "--lang", "eng;rm"],
        ["doc", "process", "x.png", "--out", "o", "--colour", "sepia"],
        ["doc", "process", "x.png", "--out", "o", "--ocr", "maybe"],
        ["doc", "process", "x.png", "--out", "o", "--dpi", "0"],
        ["doc", "process", "x.png", "--out", "o", "--name", ".."],
    ],
)
def test_bad_command_lines_are_exit_2(arguments, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "o").mkdir()
    write_pages(tmp_path, [text_scene(1)])[0].rename(tmp_path / "x.png")
    assert main(arguments) == 2


@pytest.mark.parametrize("position", ["before", "middle", "after"])
def test_verbose_is_accepted_wherever_it_is_put(tmp_path, out, position) -> None:
    pages = [str(p) for p in write_pages(tmp_path / "raw", [text_scene(1)])]
    tail = ["--out", str(out), *OFF]
    arguments = {
        "before": ["-v", "doc", "process", *pages, *tail],
        "middle": ["doc", "-v", "process", *pages, *tail],
        "after": ["doc", "process", *pages, *tail, "-v"],
    }[position]
    assert main(arguments) == 0


def test_the_help_lists_the_process_subcommand(capsys) -> None:
    assert main(["doc", "--help"]) == 0
    assert "process" in capsys.readouterr().out
