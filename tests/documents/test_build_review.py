"""Whole-pipeline behaviour: what is checked first, when to stop, and where the blank margin is."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import (
    DocumentCancelledError,
    DocumentSettings,
    OcrCancelledError,
    OcrMode,
    UnsupportedPageError,
    analyse,
    build_document,
)
from fastfoto_linux.documents.modes import ColourMode
from tests.documents.helpers import (
    DPI,
    expected_points,
    page_size_pt,
    reader,
    text_scene,
    write_pages,
)
from tests.documents.trim_helpers import mm, receipt


def settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), **changes)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    return tmp_path / "raw"


# ---- a page that cannot be decoded stops the run before any work ---------------------------


def test_a_truncated_page_stops_everything_before_any_page_is_processed(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = write_pages(raw, [text_scene(1), text_scene(2), text_scene(3)])
    data = pages[2].read_bytes()
    pages[2].write_bytes(data[: len(data) * 2 // 3])  # well into the pixel data

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a page was processed before every page was checked")

    monkeypatch.setattr(analyse, "trim_page", refuse)
    with pytest.raises(UnsupportedPageError, match=r"page-03\.png"):
        build_document(pages, settings(out))
    assert list(out.iterdir()) == []


# ---- cancel is honoured between pages --------------------------------------------------------


def test_cancelling_between_pages_stops_before_the_next_page(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    loaded: list[Path] = []
    real = analyse.load_page

    def load_then_cancel(path: Path, **kwargs: Any) -> Any:
        loaded.append(path)
        cancel.set()
        return real(path, **kwargs)

    monkeypatch.setattr(analyse, "load_page", load_then_cancel)
    pages = write_pages(raw, [text_scene(n) for n in range(4)])
    with pytest.raises(DocumentCancelledError):
        build_document(pages, settings(out), cancel=cancel)
    assert len(loaded) == 1
    assert list(out.iterdir()) == []
    assert all(page.exists() for page in pages)


def test_cancelling_during_the_checks_stops_before_the_next_page_is_decoded(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    checked: list[Path] = []
    real = analyse.inspect_page

    def check_then_cancel(path: Path, **kwargs: Any) -> Any:
        checked.append(path)
        cancel.set()
        return real(path, **kwargs)

    monkeypatch.setattr(analyse, "inspect_page", check_then_cancel)
    pages = write_pages(raw, [text_scene(n) for n in range(4)])
    with pytest.raises(DocumentCancelledError):
        build_document(pages, settings(out), cancel=cancel)
    assert len(checked) == 1
    assert list(out.iterdir()) == []


def test_a_cancel_that_is_already_set_processes_no_page(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a page was loaded after the cancel")

    monkeypatch.setattr(analyse, "load_page", refuse)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DocumentCancelledError):
        build_document(write_pages(raw, [text_scene(1)]), settings(out), cancel=cancel)


def test_stopping_during_ocr_and_between_pages_are_the_same_kind_of_stop() -> None:
    assert issubclass(OcrCancelledError, DocumentCancelledError)


# ---- trimming happens in colour, before the page is made grey or black and white -----------------


@pytest.mark.parametrize("mode", [ColourMode.GREY, ColourMode.BW])
def test_a_colour_page_is_trimmed_in_colour_before_it_is_made_grey_or_bw(
    raw: Path, out: Path, mode: ColourMode
) -> None:
    """A grey page keeps its sides and its tail (it has no hue to find the backing by), so a
    colour receipt that came out the same size in grey and in black and white was trimmed first."""
    scene = receipt()
    pages = write_pages(raw, [scene])
    sizes = {}
    for colour in (ColourMode.COLOUR, mode):
        result = build_document(pages, settings(out, colour=colour, keep_blank=True))
        sizes[colour] = page_size_pt(reader(result.pdf.read_bytes()), 0)
    assert sizes[mode] == pytest.approx(sizes[ColourMode.COLOUR], abs=0.01)
    width, height = sizes[mode]
    assert width < expected_points(scene.paper_x[1] - scene.paper_x[0] + mm(2), DPI)
    assert height <= expected_points(scene.paper_end + mm(5), DPI)
