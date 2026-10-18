"""``ffscan doc process`` and searchable text: the exit codes and what is said."""

import os
import signal
from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.documents import ocr_tools
from tests import _fake_ocrmypdf as fake
from tests.documents.helpers import reader, text_scene, write_pages

HINT = "sudo dnf install tesseract tesseract-osd"


@pytest.fixture
def pages(tmp_path: Path) -> list[Path]:
    return write_pages(tmp_path / "raw", [text_scene(1), text_scene(2)])


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


def doc(out: Path, pages, *extra: str) -> int:
    return main(["doc", "process", *map(str, pages), "--out", str(out), *extra])


def test_without_ocrmypdf_the_default_writes_the_plain_pdf_with_a_one_line_hint(
    pages, out, capsys
) -> None:
    assert doc(out, pages) == 0
    lines = capsys.readouterr().out.splitlines()
    hints = [line for line in lines if HINT in line]
    assert len(hints) == 1
    assert hints[0].startswith("searchable text: no")
    assert (out / "Document_0001.pdf").is_file()


def test_ocr_off_says_it_is_off_and_gives_no_hint(pages, out, capsys) -> None:
    assert doc(out, pages, "--ocr", "off") == 0
    text = capsys.readouterr().out
    assert HINT not in text
    assert "searchable text: no (off)" in text.splitlines()


def test_required_ocr_without_ocrmypdf_is_exit_3_before_any_work(
    pages, out, tmp_path, capsys, monkeypatch
) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("a page was read before the OCR check")

    monkeypatch.setattr("fastfoto_linux.documents.analyse.inspect_page", refuse)
    monkeypatch.setattr("fastfoto_linux.documents.analyse.load_page", refuse)
    target = tmp_path / "fresh"
    code = main(
        ["doc", "process", *map(str, pages), "--out", str(target), "--mkdir", "--ocr", "on"]
    )
    assert code == 3
    assert not target.exists()  # not even the folder was made
    err = capsys.readouterr().err
    assert HINT in err
    assert "Traceback" not in err


def test_ocr_that_works_says_yes_and_publishes_the_searchable_pdf(
    pages, out, tmp_path, monkeypatch, capsys
) -> None:
    record = tmp_path / "record.json"
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="mark", record_to=str(record))
    assert doc(out, pages, "--lang", "eng+deu") == 0
    assert "searchable text: yes" in capsys.readouterr().out.splitlines()
    assert (out / "Document_0001.pdf").read_bytes().endswith(fake.MARKER)
    argv = fake.read_record(record)["argv"]
    assert argv[:5] == ["--output-type", "pdf", "--rotate-pages", "-l", "eng+deu"]
    assert argv[5:7] == ["--rasterizer", "pypdfium"]
    assert len(reader((out / "Document_0001.pdf").read_bytes()).pages) == 2


def test_ocr_that_fails_is_exit_1_with_a_warning_and_the_plain_pdf(
    pages, out, tmp_path, monkeypatch, capsys
) -> None:
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="fail")
    assert doc(out, pages, "--ocr", "on") == 1
    captured = capsys.readouterr()
    assert "plain" in captured.err
    assert "searchable text: no" in captured.out
    pdf = out / "Document_0001.pdf"
    assert len(reader(pdf.read_bytes()).pages) == 2
    assert fake.MARKER not in pdf.read_bytes()
    assert sorted(p.name for p in out.iterdir() if p.name != ".fastfoto-linux.lock") == [pdf.name]


@pytest.mark.parametrize("verbosity", [[], ["-v"]], ids=["default", "verbose"])
def test_a_failed_ocr_is_reported_once_and_says_what_to_install(
    pages, out, monkeypatch, capsys, verbosity
) -> None:
    fake.put_on_path(out.parent / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="exit", exit_code=3)
    assert doc(out, pages, "--ocr", "on", *verbosity) == 1
    mentions = [line for line in capsys.readouterr().err.splitlines() if "searchable text" in line]
    assert len(mentions) == 1
    assert "sudo dnf install tesseract-langpack-eng tesseract-osd" in mentions[0]
    assert "status 3" in mentions[0]


def test_recognised_text_never_reaches_the_terminal(
    pages, out, tmp_path, monkeypatch, capsys
) -> None:
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    fake.configure(monkeypatch, chatter="RECOGNISED-WORDS-1234")
    assert main(["doc", "process", *map(str, pages), "--out", str(out), "--debug"]) == 0
    captured = capsys.readouterr()
    assert "RECOGNISED-WORDS-1234" not in captured.out + captured.err


def test_ctrl_c_during_ocr_is_exit_130_with_nothing_published_and_nothing_left_running(
    pages, out, tmp_path, monkeypatch, capsys
) -> None:
    record = tmp_path / "record.json"
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="hang", record_to=str(record), child=True)

    fake.when_started(record, lambda: os.kill(os.getpid(), signal.SIGINT))
    assert doc(out, pages, "--ocr", "on") == 130
    assert "interrupted" in capsys.readouterr().err
    seen = fake.read_record(record)
    assert fake.wait_until_gone(seen["pid"])
    assert fake.wait_until_gone(seen["child"])
    assert [p.name for p in out.iterdir() if p.name != ".fastfoto-linux.lock"] == []
    assert all(p.exists() for p in pages)


def ocrmypdf_without_tesseract(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The app's own ocrmypdf is there; Tesseract, a program, is not."""
    fake.put_on_path(folder, monkeypatch)
    (folder / "tesseract").unlink()


def test_without_tesseract_the_default_writes_the_plain_pdf_with_the_dnf_hint(
    pages, out, tmp_path, capsys, monkeypatch
) -> None:
    ocrmypdf_without_tesseract(tmp_path / "bin", monkeypatch)
    assert doc(out, pages) == 0
    lines = capsys.readouterr().out.splitlines()
    [hint_line] = [line for line in lines if HINT in line]
    assert "ocrmypdf is not installed" not in hint_line  # it is Tesseract that is missing
    assert fake.MARKER not in (out / "Document_0001.pdf").read_bytes()


def test_without_tesseract_on_an_immutable_system_the_hint_is_brew(
    pages, out, tmp_path, capsys, monkeypatch
) -> None:
    ocrmypdf_without_tesseract(tmp_path / "bin", monkeypatch)
    marker = tmp_path / "ostree-booted"
    marker.touch()
    monkeypatch.setattr(ocr_tools, "OSTREE_MARKER", marker)
    assert doc(out, pages) == 0
    text = capsys.readouterr().out
    assert "brew install tesseract" in text
    assert "dnf" not in text


def test_required_ocr_without_tesseract_is_exit_3_with_the_hint_and_no_traceback(
    pages, out, tmp_path, capsys, monkeypatch
) -> None:
    ocrmypdf_without_tesseract(tmp_path / "bin", monkeypatch)
    assert doc(out, pages, "--ocr", "on") == 3
    err = capsys.readouterr().err
    assert HINT in err
    assert "ocrmypdf, which is not installed" not in err  # it is Tesseract that is missing
    assert "Traceback" not in err


# -- the hint names what is missing: Tesseract, OCRmyPDF or both -------------------------------

PIP = "pip install 'fastfoto-linux[ocr]'"
MISSING = [  # ocrmypdf is there, tesseract is there, what the hint says, what it must not say
    pytest.param((False, True, [PIP, "installer"], [HINT, "dnf"]), id="ocrmypdf"),
    pytest.param((True, False, [HINT], [PIP]), id="tesseract"),
    pytest.param((False, False, [HINT, PIP], []), id="both"),
]


@pytest.fixture(params=MISSING)
def missing(request, tmp_path, monkeypatch) -> tuple[list[str], list[str]]:
    """A machine with one or both OCR parts missing; what the hint must and must not say."""
    ocrmypdf, tesseract, wanted, unwanted = request.param
    fake.ocr_machine(tmp_path / "bin", monkeypatch, ocrmypdf=ocrmypdf, tesseract=tesseract)
    return wanted, unwanted


def test_the_summary_hint_names_the_part_that_is_missing(pages, out, capsys, missing) -> None:
    wanted, unwanted = missing
    assert doc(out, pages) == 0
    [line] = [x for x in capsys.readouterr().out.splitlines() if x.startswith("searchable text:")]
    assert all(text in line for text in wanted)
    assert not any(text in line for text in unwanted)


def test_required_ocr_refused_names_the_part_that_is_missing(pages, out, capsys, missing) -> None:
    wanted, unwanted = missing
    assert doc(out, pages, "--ocr", "on") == 3
    err = capsys.readouterr().err
    assert all(text in err for text in wanted)
    assert not any(text in err for text in unwanted)
