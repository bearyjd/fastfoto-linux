"""``write_document`` with edits: several PDFs, each with a name, a number and a title; turned
pages; OCR per part; all parts or none."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from fastfoto_linux.documents import (
    AllPagesBlankError,
    DocumentCancelledError,
    DocumentSettings,
    NothingSelectedError,
    OcrMode,
    UnsupportedPageError,
)
from fastfoto_linux.documents import write as write_module
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_edit import rotate, set_included, set_part_name, toggle_split
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.write import write_document
from tests import _fake_ocrmypdf as fake
from tests.doc_synth_holes import SMALL_MM
from tests.documents.draft_helpers import LiveCounter, hand_draft
from tests.documents.helpers import (
    FIXED_TIME,
    blank_scene,
    page_size_pt,
    pdf_pixels,
    reader,
    text_scene,
    write_pages,
)


def settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF), **changes)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def _draft(tmp_path: Path, out: Path, count: int = 4, **options: Any) -> DocumentDraft:
    pages = write_pages(tmp_path / "raw", [text_scene(n) for n in range(1, count + 1)])
    return hand_draft(pages, settings(out), **options)


def _titles(result: Any) -> list[str]:
    return [reader(part.pdf.read_bytes()).metadata.title for part in result.parts]


def _names(out: Path) -> list[str]:
    return sorted(p.name for p in out.iterdir() if not p.name.startswith("."))


# ---- names, numbers, titles -------------------------------------------------------------------


def test_each_part_is_published_under_its_own_name_and_titled_with_it(
    tmp_path: Path, out: Path
) -> None:
    draft = set_part_name(toggle_split(_draft(tmp_path, out), 3), 1, "Tax return")
    draft = set_part_name(draft, 2, "Receipts")
    result = write_document(draft, settings(out), clock=lambda: FIXED_TIME)
    assert _names(out) == ["Receipts_0001.pdf", "Tax return_0001.pdf"]
    assert [(p.pdf.name, p.name, p.pages) for p in result.parts] == [
        ("Tax return_0001.pdf", "Tax return", 2),
        ("Receipts_0001.pdf", "Receipts", 2),
    ]
    assert _titles(result) == ["Tax return", "Receipts"]
    assert (result.pages_read, result.pages_in_pdf, result.pdf) == (4, 4, result.parts[0].pdf)


def test_unnamed_parts_take_the_document_name_and_their_number(tmp_path: Path, out: Path) -> None:
    draft = toggle_split(toggle_split(_draft(tmp_path, out, 6), 3), 5)
    result = write_document(draft, settings(out, name="Taxes"))
    assert _names(out) == [
        "Taxes (part 1)_0001.pdf",
        "Taxes (part 2)_0001.pdf",
        "Taxes (part 3)_0001.pdf",
    ]
    assert _titles(result) == ["Taxes (part 1)", "Taxes (part 2)", "Taxes (part 3)"]


def test_one_named_part_and_one_unnamed(tmp_path: Path, out: Path) -> None:
    draft = set_part_name(toggle_split(_draft(tmp_path, out), 3), 2, "Receipts")
    write_document(draft, settings(out))
    assert _names(out) == ["Document (part 1)_0001.pdf", "Receipts_0001.pdf"]


def test_a_single_part_keeps_the_document_name_even_after_edits(tmp_path: Path, out: Path) -> None:
    draft = set_included(_draft(tmp_path, out), 2, False)
    result = write_document(draft, settings(out))
    assert _names(out) == ["Document_0001.pdf"]
    assert (result.parts[0].pages, result.removed) == (3, (2,))


def test_a_single_part_can_be_named(tmp_path: Path, out: Path) -> None:
    result = write_document(set_part_name(_draft(tmp_path, out), 1, "Lease"), settings(out))
    assert (_names(out), _titles(result)) == (["Lease_0001.pdf"], ["Lease"])


def test_a_name_that_has_files_in_the_folder_gets_its_next_number(
    tmp_path: Path, out: Path
) -> None:
    (out / "Receipts_0007.pdf").write_bytes(b"x")
    (out / "Receipts_0002_a.jpg").write_bytes(b"x")
    draft = set_part_name(
        set_part_name(toggle_split(_draft(tmp_path, out), 3), 1, "Tax"), 2, "Receipts"
    )
    write_document(draft, settings(out))
    assert _names(out) == [
        "Receipts_0002_a.jpg",
        "Receipts_0007.pdf",
        "Receipts_0008.pdf",
        "Tax_0001.pdf",
    ]


def test_two_parts_with_the_same_name_get_consecutive_numbers(tmp_path: Path, out: Path) -> None:
    draft = set_part_name(
        set_part_name(toggle_split(_draft(tmp_path, out), 3), 1, "Pages"), 2, "pages"
    )
    write_document(draft, settings(out))
    assert _names(out) == ["Pages_0001.pdf", "pages_0002.pdf"]


def test_the_pages_of_each_part_are_the_ones_in_the_edit(tmp_path: Path, out: Path) -> None:
    draft = _draft(tmp_path, out, 5, blank={4})
    draft = toggle_split(set_included(draft, 1, False), 3)
    result = write_document(draft, settings(out))
    assert [p.pages for p in result.parts] == [1, 2]
    assert (result.dropped, result.removed) == ((4,), (1,))


# ---- nothing to write -------------------------------------------------------------------------


def test_when_the_reviewer_leaves_out_every_page_nothing_is_selected(
    tmp_path: Path, out: Path
) -> None:
    draft = _draft(tmp_path, out, 2)
    for number in (1, 2):
        draft = set_included(draft, number, False)
    with pytest.raises(NothingSelectedError, match="no page is left"):
        write_document(draft, settings(out))
    assert _names(out) == []


def test_without_edits_all_blank_is_still_the_old_error(tmp_path: Path, out: Path) -> None:
    pages = write_pages(tmp_path / "raw", [blank_scene(1), blank_scene(2)])
    draft = hand_draft(pages, settings(out), blank={1, 2})
    with pytest.raises(AllPagesBlankError, match="all 2 pages look blank"):
        write_document(draft, settings(out))


# ---- turned pages -----------------------------------------------------------------------------


@pytest.mark.parametrize("dpi", [200, 300, 600])
@pytest.mark.parametrize("turns", [1, 2, 3])
def test_a_turned_page_is_the_plain_page_turned_clockwise_pixel_for_pixel(
    dpi: int, turns: int, tmp_path: Path, out: Path
) -> None:
    scene = text_scene(1, dpi=dpi, paper_mm=SMALL_MM)
    pages = write_pages(tmp_path / "raw", [scene])
    used = settings(out, colour=ColourMode.BW, duplex=False)
    draft = hand_draft(pages, used, with_bytes=False)
    plain = write_document(draft, used)
    turned = write_document(rotate(draft, 1, turns), used)
    before = pdf_pixels(reader(plain.pdf.read_bytes()), 0)
    after = pdf_pixels(reader(turned.pdf.read_bytes()), 0)
    assert np.array_equal(after, np.rot90(before, -turns))
    width, height = page_size_pt(reader(plain.pdf.read_bytes()), 0)
    expected = (height, width) if turns % 2 else (width, height)
    assert page_size_pt(reader(turned.pdf.read_bytes()), 0) == pytest.approx(expected, abs=0.5)


def test_a_turned_page_is_read_again_even_when_it_carries_its_bytes(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = rotate(_draft(tmp_path, out, 3), 2, 1)
    counter = LiveCounter()
    monkeypatch.setattr(write_module, "load_page", counter)
    calls: list[tuple[int, int]] = []
    write_document(draft, settings(out), on_page=lambda n, total: calls.append((n, total)))
    assert (counter.loads, calls) == (1, [(2, 3)])


def test_turning_every_page_of_a_long_document_holds_one_decoded_page(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenes = [text_scene(n, dpi=300, paper_mm=SMALL_MM) for n in range(6)]
    draft = hand_draft(write_pages(tmp_path / "raw", scenes), settings(out), with_bytes=False)
    for number in range(1, 7):
        draft = rotate(draft, number, 1)
    counter = LiveCounter()
    monkeypatch.setattr(write_module, "load_page", counter)
    write_document(toggle_split(draft, 4), settings(out))
    assert (counter.loads, counter.peak) == (6, 1)


def test_a_page_brought_back_is_read_from_the_raw_pages(tmp_path: Path, out: Path) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1), blank_scene(2), text_scene(3)])
    draft = hand_draft(pages, settings(out), blank={2})
    result = write_document(set_included(draft, 2, True), settings(out))
    assert len(reader(result.pdf.read_bytes()).pages) == 3


# ---- OCR per part -----------------------------------------------------------------------------


def test_the_ocr_runs_for_every_part_with_a_limit_from_that_parts_page_count(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="mark")
    seen: list[tuple[int, float]] = []
    real = write_module.run_ocr

    def spy(plain: bytes, **kwargs: Any) -> Any:
        seen.append((kwargs["page_count"], kwargs["timeout_s"]))
        return real(plain, **kwargs)

    monkeypatch.setattr(write_module, "run_ocr", spy)
    ocr_calls: list[None] = []
    draft = toggle_split(_draft(tmp_path, out, 4), 2)  # parts of 1 and 3 pages
    result = write_document(
        draft, settings(out, ocr=OcrMode.AUTO), on_ocr=lambda: ocr_calls.append(None)
    )
    base, per_page = write_module.OCR_BASE_S, write_module.OCR_PER_PAGE_S
    assert seen == [(1, base + per_page), (3, base + 3 * per_page)]
    assert len(ocr_calls) == 2
    assert all(p.ocr.status.value == "done" for p in result.parts)
    assert all(b"fake-ocr-text-layer" in p.pdf.read_bytes() for p in result.parts)


def test_a_failed_ocr_of_one_part_still_publishes_every_part(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.put_on_path(tmp_path / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="fail")
    result = write_document(
        toggle_split(_draft(tmp_path, out, 4), 3), settings(out, ocr=OcrMode.AUTO)
    )
    assert len(_names(out)) == 2
    assert result.ok is False


# ---- all parts or none ------------------------------------------------------------------------


@pytest.mark.parametrize("stop_after", [1, 2, 3, 4])
def test_a_cancel_before_any_page_of_any_part_publishes_nothing(
    stop_after: int, tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    pages = write_pages(tmp_path / "raw", [text_scene(n) for n in range(1, 5)])
    draft = toggle_split(hand_draft(pages, settings(out), with_bytes=False), 3)
    counter = LiveCounter(lambda loads: cancel.set() if loads == stop_after else None)
    monkeypatch.setattr(write_module, "load_page", counter)
    with pytest.raises(DocumentCancelledError):
        write_document(draft, settings(out), cancel=cancel)
    assert counter.loads == stop_after
    assert _names(out) == []


def test_a_cancel_during_the_last_part_publishes_not_even_the_first(
    tmp_path: Path, out: Path
) -> None:
    cancel = threading.Event()
    calls: list[None] = []

    def clock() -> Any:
        calls.append(None)
        if len(calls) == 2:  # the second PDF is being assembled; the first is already made
            cancel.set()
        return FIXED_TIME

    draft = toggle_split(_draft(tmp_path, out), 3)
    with pytest.raises(DocumentCancelledError, match="published"):
        write_document(draft, settings(out), cancel=cancel, clock=clock)
    assert _names(out) == []


def test_an_unusable_page_in_the_last_part_publishes_nothing(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = toggle_split(
        hand_draft(
            write_pages(tmp_path / "raw", [text_scene(n) for n in range(1, 5)]),
            settings(out),
            with_bytes=False,
        ),
        3,
    )
    real = write_module.load_page
    calls: list[Path] = []

    def failing(path: Path, **kwargs: Any) -> Any:
        calls.append(path)
        if len(calls) == 4:
            raise UnsupportedPageError("page 4 is not usable")
        return real(path, **kwargs)

    monkeypatch.setattr(write_module, "load_page", failing)
    with pytest.raises(UnsupportedPageError):
        write_document(draft, settings(out))
    assert _names(out) == []
