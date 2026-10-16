"""``ffscan doc scan``: the feeder to one PDF, with a faked transport (no scanner is started)."""

import pytest

from fastfoto_linux.scanner import MAX_LENGTH_MM, Mode, Source
from tests.cli.doc_scan_helpers import (
    doc_scan,
    kept,
    kept_pages,
    visible,
)
from tests.documents.helpers import blank_scene, reader, text_scene

pytestmark = pytest.mark.usefixtures("no_real_ocr", "fixed_stamp")

LETTER_WIDTH_PT = 612  # 8.5 inches
THREE = ["page-0001.png", "page-0002.png", "page-0003.png"]


def test_a_stack_becomes_one_pdf_and_the_summary_says_what_happened(
    out, doc_transport, capsys
) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2), text_scene(3)]
    assert doc_scan(out) == 0
    pdf = out / "Document_0001.pdf"
    assert visible(out) == ["Document_0001.pdf"]
    assert len(reader(pdf.read_bytes()).pages) == 2
    lines = capsys.readouterr().out.splitlines()
    assert "pages scanned: 3" in lines
    assert "blank pages dropped: 1 (page 2)" in lines
    assert "pages in the PDF: 2" in lines
    assert "searchable text: no (off)" in lines
    assert f"file written: {pdf}" in lines
    raw = [line for line in lines if line.startswith("raw pages:")]
    assert len(raw) == 1
    assert str(kept(out)) in raw[0]
    assert "blank" in raw[0]
    assert "--discard-raw" in raw[0]
    assert kept_pages(out) == THREE


def test_after_a_clean_run_the_raw_pages_are_gone_and_the_summary_says_so(
    out, doc_transport, capsys
) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    assert doc_scan(out) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "raw pages: deleted (--keep-raw keeps them)" in lines
    assert not (out / ".raw").exists()
    assert [p.name for p in out.iterdir() if p.name != ".fastfoto-linux.lock"] == [
        "Document_0001.pdf"
    ]


def test_keep_raw_keeps_the_pages_and_says_where(out, doc_transport, capsys) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    assert doc_scan(out, "--keep-raw") == 0
    assert kept_pages(out) == THREE[:2]
    assert doc_transport.jobs[0].output_dir == kept(out)
    lines = capsys.readouterr().out.splitlines()
    assert f"raw pages: kept in {kept(out)} (you asked for them)" in lines


def test_discard_raw_deletes_them_even_when_a_blank_page_was_dropped(
    out, doc_transport, capsys
) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2)]
    assert doc_scan(out, "--discard-raw") == 0
    assert not (out / ".raw").exists()
    assert "blank pages dropped: 1 (page 2)" in capsys.readouterr().out.splitlines()
    assert visible(out) == ["Document_0001.pdf"]


def test_the_scan_is_full_length_colour_duplex_at_300_dpi_by_default(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    (job,) = doc_transport.jobs
    assert job.mode is Mode.COLOR
    assert job.source is Source.DUPLEX
    assert job.resolution == 300
    assert job.max_length_mm == MAX_LENGTH_MM
    assert job.deskew is True
    assert job.output_dir.parent == out
    assert not job.output_dir.exists()  # the temporary raw folder is gone


def test_the_scanner_environment_comes_from_the_target(out, doc_transport, monkeypatch) -> None:
    monkeypatch.setenv("FASTFOTO_TEST_MARKER", "1")
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    assert doc_transport.envs[0]["FASTFOTO_TEST_MARKER"] == "1"


def test_the_name_is_the_file_name_and_numbering_continues(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out, "--name", "Tax Return") == 0
    assert doc_scan(out, "--name", "Tax Return") == 0
    assert visible(out) == ["Tax Return_0001.pdf", "Tax Return_0002.pdf"]


def test_numbering_continues_after_a_pdf_that_is_already_there(
    tmp_path, out, doc_transport
) -> None:
    (out / "Document_0007.pdf").write_bytes(b"%PDF-earlier")
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    assert visible(out) == ["Document_0007.pdf", "Document_0008.pdf"]
    assert (out / "Document_0007.pdf").read_bytes() == b"%PDF-earlier"


def test_keep_blank_keeps_every_page(out, doc_transport, capsys) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2)]
    assert doc_scan(out, "--keep-blank") == 0
    assert "blank pages dropped: 0" in capsys.readouterr().out.splitlines()
    assert len(reader((out / "Document_0001.pdf").read_bytes()).pages) == 2
    assert not (out / ".raw").exists()


def test_a_page_without_a_resolution_is_taken_at_the_one_asked_for(out, doc_transport) -> None:
    doc_transport.dpi_in_file = False
    doc_transport.scenes = [text_scene(1, dpi=200)]  # a Letter page: 1700 pixels wide
    assert doc_scan(out, "--dpi", "200") == 0
    width = float(reader((out / "Document_0001.pdf").read_bytes()).pages[0].mediabox.width)
    assert width == pytest.approx(LETTER_WIDTH_PT, abs=0.5)


def test_verbose_logs_each_page(out, doc_transport, capsys) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    assert doc_scan(out, "-v") == 0
    err = capsys.readouterr().err
    assert "page 1 scanned" in err
    assert "page 2 scanned" in err


def test_the_pages_are_scanned_into_a_hidden_folder_of_the_output_folder(
    out, doc_transport
) -> None:
    doc_transport.scenes = [text_scene(1)]
    assert doc_scan(out) == 0
    assert doc_transport.jobs[0].output_dir.name.startswith(".ffscan-raw-")
