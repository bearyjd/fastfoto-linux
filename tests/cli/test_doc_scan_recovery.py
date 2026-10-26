"""``ffscan doc scan`` after a part-way scan: the printed command makes the PDF as printed."""

import shlex
from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.scanner import ScanError
from tests.cli.doc_scan_helpers import doc_scan, kept
from tests.documents.helpers import reader, text_scene

pytestmark = pytest.mark.usefixtures("no_real_ocr", "fixed_stamp")

COMMAND = "ffscan doc process"


@pytest.fixture
def spaced(tmp_path: Path) -> Path:
    """An output folder with a space in its name, so that the quoting is part of the test."""
    root = tmp_path / "my scans"
    root.mkdir()
    return root


def jam_after(transport, finished: int) -> None:
    """Three pages are scanned and the scanner fails after ``finished`` of them; the third is cut
    off mid-write, as it is when a cover is opened."""
    transport.scenes = [text_scene(1), text_scene(2), text_scene(3)]
    transport.pages_before_failure = finished
    transport.truncate_page = 3
    transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)


def printed_command(err: str) -> str:
    lines = [line for line in err.splitlines() if line.startswith(COMMAND)]
    assert len(lines) == 1, err
    return lines[0]


def expected(root: Path, finished: int, *options: str) -> str:
    pages = [str(kept(root) / f"page-{number:04d}.png") for number in range(1, finished + 1)]
    return shlex.join([*COMMAND.split(), *pages, "--out", str(root), *options])


def test_the_hint_is_the_exact_command_with_the_pages_that_were_finished(
    spaced, doc_transport, capsys
) -> None:
    jam_after(doc_transport, 2)
    assert doc_scan(spaced) == 1
    err = capsys.readouterr().err
    assert printed_command(err) == expected(spaced, 2, "--dpi", "300", "--ocr", "off")
    assert "page-0003" not in err  # the page cut off mid-write is not offered
    assert "to make one from the 2 pages scanned" in err


def test_one_page_is_not_pages(spaced, doc_transport, capsys) -> None:
    jam_after(doc_transport, 1)
    assert doc_scan(spaced) == 1
    err = capsys.readouterr().err
    assert "to make one from the 1 page scanned" in err
    assert "1 pages" not in err


def test_the_printed_command_makes_the_pdf_from_the_good_pages(
    spaced, doc_transport, capsys
) -> None:
    jam_after(doc_transport, 2)
    assert doc_scan(spaced) == 1
    command = printed_command(capsys.readouterr().err)
    cut_off = kept(spaced) / "page-0003.png"
    before = cut_off.read_bytes()
    assert not [p for p in spaced.iterdir() if p.suffix == ".pdf"]

    argv = shlex.split(command)
    assert argv[0] == "ffscan"
    assert main(argv[1:]) == 0

    assert sorted(p.name for p in spaced.iterdir() if p.suffix == ".pdf") == ["Document_0001.pdf"]
    assert len(reader((spaced / "Document_0001.pdf").read_bytes()).pages) == 2
    assert cut_off.read_bytes() == before  # the raw pages are never changed


def test_every_option_that_is_not_the_default_is_in_the_command(
    spaced, doc_transport, capsys
) -> None:
    jam_after(doc_transport, 2)
    options = ["--colour", "grey", "--name", "Tax Return", "--keep-blank", "--dpi", "600"]
    options += ["--cleanup", "light"]
    assert doc_scan(spaced, *options, "--lang", "eng+deu") == 1
    command = printed_command(capsys.readouterr().err)
    assert command == expected(
        spaced,
        2,
        "--dpi",
        "600",
        "--colour",
        "grey",
        "--cleanup",
        "light",
        "--name",
        "Tax Return",
        "--ocr",
        "off",
        "--lang",
        "eng+deu",
        "--keep-blank",
    )
    assert main(shlex.split(command)[1:]) == 0
    assert [p.name for p in spaced.iterdir() if p.suffix == ".pdf"] == ["Tax Return_0001.pdf"]


def test_the_default_options_are_left_out(spaced, doc_transport, capsys) -> None:
    jam_after(doc_transport, 2)
    assert doc_scan(spaced, "--ocr", "auto", "--colour", "colour", "--lang", "eng") == 1
    command = printed_command(capsys.readouterr().err)
    assert command == expected(spaced, 2, "--dpi", "300")


def test_no_command_is_printed_when_no_page_was_finished(spaced, doc_transport, capsys) -> None:
    doc_transport.failure = lambda pages: ScanError("could not start", returncode=1, pages=pages)
    assert doc_scan(spaced) == 1
    assert COMMAND not in capsys.readouterr().err
