"""``ffscan doc``: pages pair as the two sides of sheets unless ``--simplex``, so that holes through
the paper (staples, punches) do not keep a blank back."""

import shlex
from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.scanner import ScanError
from tests.cli.doc_scan_helpers import doc_scan, kept, visible
from tests.documents.helpers import reader, write_pages
from tests.documents.holes_helpers import stapled_sheet

pytestmark = pytest.mark.usefixtures("no_real_ocr", "fixed_stamp")

OFF = ["--ocr", "off"]


def pdf_pages(out: Path) -> int:
    return len(reader((out / "Document_0001.pdf").read_bytes()).pages)


def process(out: Path, pages: list[Path], *extra: str) -> int:
    return main(["doc", "process", *map(str, pages), "--out", str(out), *OFF, *extra])


@pytest.fixture
def stapled(tmp_path: Path) -> list[Path]:
    return write_pages(tmp_path / "raw", [*stapled_sheet(1)])


def test_process_pairs_the_pages_by_default_and_drops_the_back_with_only_holes(
    out: Path, stapled: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert process(out, stapled) == 0
    assert "blank pages dropped: 1 (page 2)" in capsys.readouterr().out.splitlines()
    assert pdf_pages(out) == 1


def test_process_simplex_takes_every_page_for_a_front(
    out: Path, stapled: list[Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert process(out, stapled, "--simplex") == 0
    assert "blank pages dropped: 0" in capsys.readouterr().out.splitlines()
    assert pdf_pages(out) == 2


def test_process_says_in_its_help_that_it_pairs_pages_unless_simplex(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doc", "process", "--help"]) == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "--simplex" in text
    assert "paired in order, 1+2, 3+4" in text
    assert "must start with a front" in text
    assert "holes through the paper" in text


def test_scan_pairs_the_pages_it_scanned_both_sides_of(out: Path, doc_transport) -> None:
    doc_transport.scenes = list(stapled_sheet(1))
    assert doc_scan(out) == 0
    assert pdf_pages(out) == 1


def test_scan_simplex_pairs_nothing(out: Path, doc_transport) -> None:
    doc_transport.scenes = list(stapled_sheet(1))
    assert doc_scan(out, "--simplex") == 0
    assert pdf_pages(out) == 2
    assert visible(out) == ["Document_0001.pdf"]


@pytest.fixture
def spaced(tmp_path: Path) -> Path:
    root = tmp_path / "my scans"
    root.mkdir()
    return root


def jam(transport, *, simplex: bool) -> None:
    transport.scenes = list(stapled_sheet(1))
    transport.pages_before_failure = 2
    transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)


def printed(err: str) -> list[str]:
    lines = [line for line in err.splitlines() if line.startswith("ffscan doc process")]
    assert len(lines) == 1, err
    return shlex.split(lines[0])


def test_the_recovery_command_of_a_simplex_scan_says_simplex(
    spaced: Path, doc_transport, capsys: pytest.CaptureFixture[str]
) -> None:
    jam(doc_transport, simplex=True)
    assert doc_scan(spaced, "--simplex") == 1
    argv = printed(capsys.readouterr().err)
    assert argv[-1] == "--simplex"
    assert main(argv[1:]) == 0
    assert pdf_pages(spaced) == 2  # the printed command makes the PDF the scan would have made


def test_the_recovery_command_of_a_duplex_scan_does_not(
    spaced: Path, doc_transport, capsys: pytest.CaptureFixture[str]
) -> None:
    jam(doc_transport, simplex=False)
    assert doc_scan(spaced) == 1
    argv = printed(capsys.readouterr().err)
    assert "--simplex" not in argv
    assert main(argv[1:]) == 0
    assert pdf_pages(spaced) == 1
    assert kept(spaced).is_dir()
