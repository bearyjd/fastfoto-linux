"""``ffscan doc scan`` over the real runner, a fake ``scanimage`` that writes real PNG pages
from synthetic documents and a fake ``ocrmypdf``: two subprocesses, nothing mocked in between."""

import json
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.cli import cmd_doc
from fastfoto_linux.scanner import run_scan
from tests import _fake_ocrmypdf as fake
from tests import _fake_scanimage as fake_scanimage
from tests.cli.doc_scan_helpers import HINT, doc_scan, kept, kept_pages, visible
from tests.doc_synth import LETTER_MM, Scene
from tests.documents.helpers import (
    blank_scene,
    image_object,
    page_size_pt,
    reader,
    text_scene,
    write_pages,
)
from tests.documents.trim_helpers import RECEIPT_MM, receipt

pytestmark = pytest.mark.usefixtures("fixed_stamp")

# The real runner, taken before the tests' guards replace the names it is known by.
REAL_RUN_SCAN = run_scan
SCAN_TIMEOUT_S = 30.0
POINTS_PER_MM = 72 / 25.4
DPI = 200  # small pages: the whole run stays well under a few seconds


@pytest.fixture
def feed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doc_transport) -> Callable[..., Path]:
    """Load the fake scanner with ``scenes`` and make the command use the real runner; the
    result is the file that receives scanimage's argv. ``ocrmypdf`` is on PATH only when asked
    (``ocr_spec`` says what it does)."""

    def load(scenes: list[Scene], ocr_spec: dict[str, Any] | None = None, **spec: Any) -> Path:
        record = tmp_path / "scanimage.json"
        sources = [str(p) for p in write_pages(tmp_path / "sources", scenes)]
        bin_dir = fake_scanimage.install(tmp_path / "bin")
        env = fake_scanimage.fake_env(bin_dir, record_to=str(record), page_sources=sources, **spec)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        if ocr_spec is not None:
            fake.put_on_path(bin_dir, monkeypatch)  # the same folder: both fakes on PATH
            fake.configure(monkeypatch, **ocr_spec)
        monkeypatch.setattr(cmd_doc, "run_scan", partial(REAL_RUN_SCAN, timeout_s=SCAN_TIMEOUT_S))
        return record

    return load


def pdf_of(out: Path):
    return reader((out / "Document_0001.pdf").read_bytes())


def test_a_stack_from_the_fake_scanner_becomes_a_pdf_without_the_blank_back(
    out, feed, capsys
) -> None:
    record = feed([text_scene(1), blank_scene(2), text_scene(3)])
    assert doc_scan(out, "--ocr", "off", "--dpi", str(DPI)) == 0
    assert len(pdf_of(out).pages) == 2
    argv = json.loads(record.read_text())["argv"]
    assert argv[argv.index("--mode") + 1] == "Color"
    assert argv[argv.index("--resolution") + 1] == str(DPI)
    assert "blank pages dropped: 1 (page 2)" in capsys.readouterr().out.splitlines()
    assert kept_pages(out) == ["page-0001.png", "page-0002.png", "page-0003.png"]


# --- searchable text ----------------------------------------------------------------------------


def test_searchable_text_that_works_is_yes_and_the_raw_pages_go(out, feed, capsys) -> None:
    feed([text_scene(1), text_scene(2)], ocr_spec={"mode": "mark"})
    assert doc_scan(out, "--ocr", "on", "--lang", "eng+deu", "--dpi", str(DPI)) == 0
    assert "searchable text: yes" in capsys.readouterr().out.splitlines()
    assert (out / "Document_0001.pdf").read_bytes().endswith(fake.MARKER)
    assert not (out / ".raw").exists()


def test_searchable_text_that_fails_is_exit_1_with_the_plain_pdf_and_the_pages_kept(
    out, feed, capsys
) -> None:
    feed([text_scene(1), text_scene(2)], ocr_spec={"mode": "fail"})
    assert doc_scan(out, "--ocr", "on", "--discard-raw", "--dpi", str(DPI)) == 1
    captured = capsys.readouterr()
    assert "plain" in captured.err
    assert "searchable text: no" in captured.out
    assert fake.MARKER not in (out / "Document_0001.pdf").read_bytes()
    assert len(pdf_of(out).pages) == 2
    assert f"raw pages: kept in {kept(out)} (searchable text could not be added)" in (
        captured.out.splitlines()
    )
    assert kept_pages(out) == ["page-0001.png", "page-0002.png"]


def test_without_ocrmypdf_the_default_writes_the_plain_pdf_with_one_hint(out, feed, capsys) -> None:
    feed([text_scene(1)], ocr_spec=None)
    assert doc_scan(out, "--ocr", "auto", "--dpi", str(DPI)) == 0
    lines = capsys.readouterr().out.splitlines()
    hints = [line for line in lines if HINT in line]
    assert len(hints) == 1
    assert hints[0].startswith("searchable text: no")
    assert visible(out) == ["Document_0001.pdf"]
    assert "raw pages: deleted (--keep-raw keeps them)" in lines


# --- the page is trimmed in colour, and only then made grey or black and white --------------------


@pytest.mark.parametrize(
    ("colour", "colour_space", "codec"),
    [
        ("colour", "/DeviceRGB", "/DCTDecode"),
        ("grey", "/DeviceGray", "/DCTDecode"),
        ("bw", "/DeviceGray", ["/CCITTFaxDecode"]),
    ],
)
def test_a_receipt_loses_its_backing_whatever_the_pdf_colour_because_it_is_scanned_in_colour(
    out, feed, colour, colour_space, codec
) -> None:
    feed([receipt(offset_mm=60.0)])
    assert doc_scan(out, "--colour", colour, "--dpi", str(DPI)) == 0
    pdf = pdf_of(out)
    width, _ = page_size_pt(pdf, 0)
    assert width == pytest.approx(RECEIPT_MM[0] * POINTS_PER_MM, abs=3)  # not the 216 mm frame
    assert width < LETTER_MM[0] * POINTS_PER_MM / 2
    image = image_object(pdf, 0)
    assert image["/ColorSpace"] == colour_space
    assert image["/Filter"] == codec
