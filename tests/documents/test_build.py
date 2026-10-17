"""The whole pipeline from page files to a published PDF."""

import fcntl
import hashlib
import os
import tempfile
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from fastfoto_linux.documents import (
    AllPagesBlankError,
    ColourMode,
    DocumentError,
    DocumentSettings,
    OcrCancelledError,
    OcrMissingError,
    OcrMode,
    OcrStatus,
    UnsupportedPageError,
    build,
    build_document,
)
from fastfoto_linux.output.files import LOCK_NAME
from tests import _fake_ocrmypdf as fake
from tests.doc_synth import LEGAL_MM, write_png
from tests.documents.helpers import (
    DPI,
    FIXED_TIME,
    blank_scene,
    image_object,
    page_size_pt,
    reader,
    text_scene,
    write_pages,
)


def settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), **changes)


def visible(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def hidden(folder: Path) -> list[str]:
    return sorted(
        p.name for p in folder.iterdir() if p.name.startswith(".") and p.name != LOCK_NAME
    )


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture
def fake_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fake.put_on_path(tmp_path / "bin", monkeypatch)


# ---- pages in, pages out ---------------------------------------------------------------------


def test_blank_backs_are_dropped_and_reported_by_page_number(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2), text_scene(3), blank_scene(4)])
    result = build_document(pages, settings(out))
    assert result.pages_read == 4
    assert result.dropped == (2, 4)
    assert result.pages_in_pdf == 2
    assert result.pdf == out / "Document_0001.pdf"
    assert len(reader(result.pdf.read_bytes()).pages) == 2
    assert visible(out) == ["Document_0001.pdf"]
    assert result.ocr.status is OcrStatus.SKIPPED
    assert result.ok


def test_keep_blank_keeps_every_page(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2), text_scene(3)])
    result = build_document(pages, settings(out, keep_blank=True))
    assert result.dropped == ()
    assert result.pages_in_pdf == 3
    assert len(reader(result.pdf.read_bytes()).pages) == 3


def test_when_every_page_is_blank_nothing_is_written(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [blank_scene(1), blank_scene(2)])
    with pytest.raises(AllPagesBlankError, match="blank"):
        build_document(pages, settings(out))
    assert list(out.iterdir()) == []


def test_pages_keep_the_order_they_were_given_and_their_own_size(raw: Path, out: Path) -> None:
    legal = text_scene(1, paper_mm=LEGAL_MM)
    pages = write_pages(raw, [text_scene(2), legal])
    pdf = reader(build_document(pages, settings(out)).pdf.read_bytes())
    assert page_size_pt(pdf, 0) == pytest.approx((612.0, 792.0), abs=1)
    assert page_size_pt(pdf, 1) == pytest.approx((612.0, 1008.0), abs=1)


def test_the_requested_colour_mode_reaches_the_pdf(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1)])
    expected = {
        ColourMode.COLOUR: ("/DCTDecode", "/DeviceRGB"),
        ColourMode.GREY: ("/DCTDecode", "/DeviceGray"),
        ColourMode.BW: (["/CCITTFaxDecode"], "/DeviceGray"),
    }
    for mode, (codec, space) in expected.items():
        result = build_document(pages, settings(out, colour=mode))
        image = image_object(reader(result.pdf.read_bytes()), 0)
        assert (image["/Filter"], image["/ColorSpace"]) == (codec, space)


def test_the_name_titles_the_pdf_and_names_the_file(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1)])
    result = build_document(pages, settings(out, name="Tax Return/2025"))
    assert result.pdf.name == "Tax Return 2025_0001.pdf"
    assert reader(result.pdf.read_bytes()).metadata.title == "Tax Return 2025"


def test_metadata_carries_the_creation_time_and_producer(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1)])
    result = build_document(pages, settings(out), clock=lambda: FIXED_TIME)
    info = reader(result.pdf.read_bytes()).metadata
    assert info.creation_date == FIXED_TIME
    assert info.producer == "fastfoto-linux"


def test_pages_without_a_resolution_use_the_fallback_or_stop(raw: Path, out: Path) -> None:
    raw.mkdir()
    page = write_png(raw / "bare.png", text_scene(1).image, dpi=None)
    with pytest.raises(UnsupportedPageError, match="resolution"):
        build_document([page], settings(out))
    result = build_document([page], settings(out, fallback_dpi=DPI))
    assert page_size_pt(reader(result.pdf.read_bytes()), 0) == pytest.approx((612.0, 792.0), abs=1)


def test_input_files_are_never_touched(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2)])

    def fingerprint() -> list[tuple[str, int]]:
        return [(hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in pages]

    before = fingerprint()
    build_document(pages, settings(out))
    assert fingerprint() == before
    assert sorted(p.name for p in raw.iterdir()) == [p.name for p in pages]


def test_a_bad_language_list_is_refused_before_any_page_is_read(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1)])
    with pytest.raises(ValueError, match="language"):
        build_document(pages, settings(out, langs="eng;rm"))  # even with OCR off
    assert list(out.iterdir()) == []


def test_no_pages_is_an_error(out: Path) -> None:
    with pytest.raises(DocumentError, match="no pages"):
        build_document([], settings(out))


# ---- checks happen before work, work happens page by page ----------------------------------


def test_an_unusable_page_stops_everything_before_any_page_is_processed(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = write_pages(raw, [text_scene(1), text_scene(2), text_scene(3)])
    Image.new("RGBA", (50, 50)).save(pages[1], "PNG", dpi=(DPI, DPI))
    loaded: list[Path] = []
    real = build.load_page

    def spy(path: Path, **kwargs: Any) -> Any:
        loaded.append(path)
        return real(path, **kwargs)

    monkeypatch.setattr(build, "load_page", spy)
    with pytest.raises(UnsupportedPageError, match=r"page-02\.png"):
        build_document(pages, settings(out))
    assert loaded == []
    assert list(out.iterdir()) == []


def test_pages_are_loaded_and_encoded_one_at_a_time(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_load, real_encode = build.load_page, build.encode_page

    def load(*args: Any, **kwargs: Any) -> Any:
        events.append("load")
        return real_load(*args, **kwargs)

    def encode(*args: Any, **kwargs: Any) -> Any:
        events.append("encode")
        return real_encode(*args, **kwargs)

    monkeypatch.setattr(build, "load_page", load)
    monkeypatch.setattr(build, "encode_page", encode)
    pages = write_pages(raw, [text_scene(n) for n in range(4)])
    build_document(pages, settings(out))
    assert events == ["load", "encode"] * 4


# ---- OCR ----------------------------------------------------------------------------------


def test_required_ocr_that_is_missing_stops_before_a_single_page_is_read(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a page was read before the OCR check")

    monkeypatch.setattr(build, "inspect_page", refuse)
    monkeypatch.setattr(build, "load_page", refuse)
    pages = write_pages(raw, [text_scene(1)])
    with pytest.raises(OcrMissingError, match="OCRmyPDF"):
        build_document(pages, settings(out, ocr=OcrMode.ON))
    assert list(out.iterdir()) == []


def test_automatic_ocr_without_ocrmypdf_still_writes_the_plain_pdf(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1)])
    result = build_document(pages, settings(out, ocr=OcrMode.AUTO))
    assert result.ocr.status is OcrStatus.UNAVAILABLE
    assert result.ok
    assert result.pdf.exists()
    assert result.ocr.detail == "OCRmyPDF and Tesseract are not installed"


def test_automatic_ocr_without_tesseract_says_it_is_tesseract_that_is_missing(
    raw: Path, out: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    (tmp_path / "bin" / "tesseract").unlink()
    pages = write_pages(raw, [text_scene(1)])
    result = build_document(pages, settings(out, ocr=OcrMode.AUTO))
    assert result.ocr.status is OcrStatus.UNAVAILABLE
    assert result.ocr.detail == "Tesseract is not installed"


def test_required_ocr_without_tesseract_says_it_is_tesseract_that_is_missing(
    raw: Path, out: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    (tmp_path / "bin" / "tesseract").unlink()
    pages = write_pages(raw, [text_scene(1)])
    with pytest.raises(OcrMissingError, match="Tesseract is not installed") as raised:
        build_document(pages, settings(out, ocr=OcrMode.ON))
    assert "OCRmyPDF" not in str(raised.value)


def test_ocr_that_works_publishes_the_searchable_pdf(
    raw: Path, out: Path, fake_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = tmp_path / "system-tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, mode="mark", record_to=str(record))
    pages = write_pages(raw, [text_scene(1), text_scene(2)])
    result = build_document(pages, settings(out, ocr=OcrMode.AUTO, langs="eng+deu"))
    assert result.ocr.status is OcrStatus.DONE
    assert result.ok
    assert result.pdf.read_bytes().endswith(fake.MARKER)
    argv = fake.read_record(record)["argv"]
    assert argv[3:5] == ["-l", "eng+deu"]
    assert Path(argv[-2]).parent.parent == temp  # staged in a private temporary folder ...
    assert not Path(argv[-2]).is_relative_to(out)  # ... that is not in the output folder
    assert list(temp.iterdir()) == []
    assert visible(out) == ["Document_0001.pdf"]
    assert hidden(out) == []


@pytest.mark.usefixtures("fake_on_path")
@pytest.mark.parametrize(
    ("mode", "status"),
    [("fail", OcrStatus.FAILED), ("garbage", OcrStatus.FAILED), ("hang", OcrStatus.TIMED_OUT)],
)
def test_ocr_that_fails_still_publishes_the_plain_pdf(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch, mode: str, status: OcrStatus
) -> None:
    fake.configure(monkeypatch, mode=mode)
    pages = write_pages(raw, [text_scene(1), text_scene(2)])
    result = build_document(pages, settings(out, ocr=OcrMode.ON, ocr_timeout_s=1.5))
    assert result.ocr.status is status
    assert not result.ok
    assert result.ocr.detail
    assert len(reader(result.pdf.read_bytes()).pages) == 2
    assert fake.MARKER not in result.pdf.read_bytes()
    assert hidden(out) == []


def test_ocr_off_never_starts_ocrmypdf(
    raw: Path, out: Path, fake_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, record_to=str(record))
    build_document(write_pages(raw, [text_scene(1)]), settings(out, ocr=OcrMode.OFF))
    assert not record.exists()


def test_the_folder_lock_is_free_while_ocr_runs(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch, fake_on_path: Path
) -> None:
    real = build.run_ocr
    probed: list[bool] = []

    def probe(*args: Any, **kwargs: Any) -> Any:
        fd = os.open(out / LOCK_NAME, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if someone holds it
            probed.append(True)
        finally:
            os.close(fd)
        return real(*args, **kwargs)

    monkeypatch.setattr(build, "run_ocr", probe)
    build_document(write_pages(raw, [text_scene(1)]), settings(out, ocr=OcrMode.ON))
    assert probed == [True]


def test_cancelling_during_ocr_publishes_nothing_and_leaves_nothing_running(
    raw: Path, out: Path, fake_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, mode="hang", record_to=str(record), child=True)
    cancel = threading.Event()
    fake.when_started(record, cancel.set)
    pages = write_pages(raw, [text_scene(1)])
    with pytest.raises(OcrCancelledError):
        build_document(pages, settings(out, ocr=OcrMode.ON), cancel=cancel)
    seen = fake.read_record(record)
    assert fake.wait_until_gone(seen["pid"])
    assert fake.wait_until_gone(seen["child"])
    assert visible(out) == []
    assert hidden(out) == []
    assert all(p.exists() for p in pages)


def test_running_again_makes_a_new_numbered_file(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2)])
    first = build_document(pages, settings(out))
    second = build_document(pages, settings(out))
    assert (first.pdf.name, second.pdf.name) == ("Document_0001.pdf", "Document_0002.pdf")
    assert first.pdf.read_bytes().startswith(b"%PDF-")
