"""``build_document`` tells a front end which page it is on and when the OCR starts."""

import threading
from pathlib import Path

import pytest

from fastfoto_linux.documents import (
    DocumentCancelledError,
    DocumentSettings,
    OcrMode,
    build_document,
)
from tests import _fake_ocrmypdf as fake
from tests.documents.helpers import blank_scene, text_scene, write_pages


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def settings(out: Path, **changes: object) -> DocumentSettings:
    return DocumentSettings(output_root=out, **{"ocr": OcrMode.OFF, **changes})


def test_every_page_is_announced_with_its_number_and_the_total(tmp_path: Path, out: Path) -> None:
    pages = write_pages(tmp_path, [text_scene(1), blank_scene(2), text_scene(3)])
    seen: list[tuple[int, int]] = []
    build_document(pages, settings(out), on_page=lambda number, total: seen.append((number, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_a_page_that_is_dropped_as_blank_is_announced_too(tmp_path: Path, out: Path) -> None:
    pages = write_pages(tmp_path, [text_scene(1), blank_scene(2)])
    seen: list[int] = []
    result = build_document(pages, settings(out), on_page=lambda number, _: seen.append(number))
    assert result.dropped == (2,)
    assert seen == [1, 2]


def test_a_cancel_stops_the_announcements_with_the_build(tmp_path: Path, out: Path) -> None:
    cancel = threading.Event()
    pages = write_pages(tmp_path, [text_scene(n) for n in range(1, 5)])
    seen: list[int] = []

    def on_page(number: int, total: int) -> None:
        seen.append(number)
        if number == 2:
            cancel.set()

    with pytest.raises(DocumentCancelledError):
        build_document(pages, settings(out), cancel=cancel, on_page=on_page)
    assert seen == [1, 2]


def test_without_ocr_nothing_says_the_text_layer_starts(tmp_path: Path, out: Path) -> None:
    pages = write_pages(tmp_path, [text_scene(1)])
    started: list[str] = []
    build_document(pages, settings(out, ocr=OcrMode.OFF), on_ocr=lambda: started.append("ocr"))
    assert started == []


def test_ocr_is_announced_once_after_the_last_page(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="mark")
    pages = write_pages(tmp_path, [text_scene(1), text_scene(2)])
    events: list[str] = []
    build_document(
        pages,
        settings(out, ocr=OcrMode.ON),
        on_page=lambda number, _: events.append(f"page {number}"),
        on_ocr=lambda: events.append("ocr"),
    )
    assert events == ["page 1", "page 2", "ocr"]
