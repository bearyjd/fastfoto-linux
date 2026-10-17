"""Holes through the paper in a whole document: pages pair as sheets (1, 2), (3, 4) ..., a sheet
is worked on at a time, and what is not paired (simplex, the odd last page) is judged as ever."""

import threading
import weakref
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import (
    DocumentCancelledError,
    DocumentResult,
    DocumentSettings,
    OcrMode,
    build,
    build_document,
)
from tests.doc_synth import Scene
from tests.doc_synth_holes import sheet
from tests.documents.helpers import write_pages
from tests.documents.holes_helpers import STAPLED_DPI, stapled_sheet, text

DPI = STAPLED_DPI


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def run(tmp_path: Path, out: Path, scenes: list[Scene], **changes: Any) -> DocumentResult:
    pages = write_pages(tmp_path / "raw", scenes)
    return build_document(pages, DocumentSettings(output_root=out, ocr=OcrMode.OFF, **changes))


def test_a_back_whose_only_marks_are_staple_holes_is_left_out(tmp_path: Path, out: Path) -> None:
    result = run(tmp_path, out, [*stapled_sheet(1)])
    assert (result.dropped, result.pages_in_pdf) == ((2,), 1)


def test_a_sheet_that_is_nothing_but_holes_is_left_out_on_both_sides(
    tmp_path: Path, out: Path
) -> None:
    scenes = [*stapled_sheet(1), *stapled_sheet(3, text_front=False)]
    result = run(tmp_path, out, scenes)
    assert (result.dropped, result.pages_in_pdf) == ((2, 3, 4), 1)


def test_keep_blank_keeps_the_holes_pages(tmp_path: Path, out: Path) -> None:
    result = run(tmp_path, out, [*stapled_sheet(1)], keep_blank=True)
    assert (result.dropped, result.pages_in_pdf) == ((), 2)


def test_without_pairing_nothing_is_a_hole_and_every_page_stays(tmp_path: Path, out: Path) -> None:
    scenes = [*stapled_sheet(1), *stapled_sheet(3, text_front=False)]
    result = run(tmp_path, out, scenes, duplex=False)
    assert (result.dropped, result.pages_in_pdf) == ((), 4)


def test_the_odd_last_page_has_no_other_side_and_is_kept(tmp_path: Path, out: Path) -> None:
    last = stapled_sheet(3, text_front=False)[0]
    result = run(tmp_path, out, [*stapled_sheet(1), last])
    assert (result.dropped, result.pages_in_pdf) == ((2,), 2)


def test_pages_that_pair_wrongly_keep_a_back_whose_partner_has_no_holes(
    tmp_path: Path, out: Path
) -> None:
    """An extra page first: the pages pair (1, 2), (3, 4), (5), so the back of the stapled sheet
    (page 3) meets the next front (page 4), which has no holes; page 5 is a blank odd last page."""
    extra = sheet(DPI, [text], seed=7)[0]
    front, back = stapled_sheet(1)
    next_front, next_back = sheet(DPI, [text], [], seed=9)
    result = run(tmp_path, out, [extra, front, back, next_front, next_back])
    assert (result.dropped, result.pages_in_pdf) == ((5,), 4)


def test_a_cancel_between_the_two_pages_of_a_sheet_stops_before_the_second(
    tmp_path: Path, out: Path
) -> None:
    cancel = threading.Event()
    seen: list[int] = []

    def on_page(number: int, total: int) -> None:
        seen.append(number)
        if number == 3:
            cancel.set()

    pages = write_pages(tmp_path / "raw", [*stapled_sheet(1), *stapled_sheet(3)])
    with pytest.raises(DocumentCancelledError):
        build_document(
            pages,
            DocumentSettings(output_root=out, ocr=OcrMode.OFF),
            cancel=cancel,
            on_page=on_page,
        )
    assert seen == [1, 2, 3]
    assert list(out.iterdir()) == []


def test_a_duplex_document_is_loaded_and_encoded_a_sheet_at_a_time(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
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
    scenes = [text(sheet(DPI, seed=n)[0]) for n in range(4)]
    run(tmp_path, out, scenes)
    assert events == ["load", "load", "encode", "encode"] * 2


def test_at_most_two_pages_are_in_memory_at_once(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alive: list[weakref.ref] = []
    seen_alive: list[int] = []
    real_load = build.load_page

    def load(*args: Any, **kwargs: Any) -> Any:
        seen_alive.append(sum(ref() is not None for ref in alive))
        page = real_load(*args, **kwargs)
        alive.append(weakref.ref(page.pixels))
        return page

    monkeypatch.setattr(build, "load_page", load)
    run(tmp_path, out, [text(sheet(DPI, seed=n)[0]) for n in range(6)])
    assert seen_alive == [0, 1, 0, 1, 0, 1]


def test_progress_is_reported_for_each_page_just_before_it_is_encoded(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In page order, though a sheet's two pages are loaded together to be judged by each other:
    the progress of page 2 does not come before page 1 is encoded."""
    events: list[object] = []
    real_encode = build.encode_page

    def encode(*args: Any, **kwargs: Any) -> Any:
        events.append("encode")
        return real_encode(*args, **kwargs)

    monkeypatch.setattr(build, "encode_page", encode)
    pages = write_pages(tmp_path / "raw", [text(sheet(DPI, seed=n)[0]) for n in range(4)])
    settings = DocumentSettings(output_root=out, ocr=OcrMode.OFF)
    build_document(pages, settings, on_page=lambda number, total: events.append(number))
    assert events == [1, "encode", 2, "encode", 3, "encode", 4, "encode"]


def test_a_cancel_seen_with_the_first_page_of_a_sheet_stops_before_its_second(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cancel check is made before each page in turn, so page 1 was processed and the message
    names page 2, not a page that nothing had begun."""
    cancel = threading.Event()
    encoded: list[str] = []
    real_encode = build.encode_page

    def encode(*args: Any, **kwargs: Any) -> Any:
        encoded.append("page")
        return real_encode(*args, **kwargs)

    monkeypatch.setattr(build, "encode_page", encode)
    pages = write_pages(tmp_path / "raw", [text(sheet(DPI, seed=n)[0]) for n in range(4)])
    settings = DocumentSettings(output_root=out, ocr=OcrMode.OFF)
    with pytest.raises(DocumentCancelledError, match="stopped before page 2 of 4 was processed"):
        build_document(pages, settings, cancel=cancel, on_page=lambda number, total: cancel.set())
    assert encoded == ["page"]
