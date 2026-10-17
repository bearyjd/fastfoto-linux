"""``analyse_document``: the checks, then the verdict and the bytes of every page, a sheet at a
time. The verdicts are the golden table's, the bytes are what ``encode_page`` makes."""

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from fastfoto_linux.documents import (
    DocumentCancelledError,
    DocumentError,
    DocumentSettings,
    OcrMode,
    UnsupportedPageError,
)
from fastfoto_linux.documents import analyse as analyse_module
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft import TrimBox
from fastfoto_linux.documents.encode import encode_page
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import Scene, paper_scene, write_png
from tests.doc_synth_holes import SMALL_MM
from tests.documents.draft_helpers import LiveCounter
from tests.documents.golden_cases import scene_pairs
from tests.documents.helpers import blank_scene, text_scene, write_pages

GOLDEN: dict[str, bool] = json.loads(
    (Path(__file__).parent / "golden_verdicts.json").read_text(encoding="utf-8")
)
FIXTURE_LABELS = sorted({key.split(" | ")[0] for key in GOLDEN if not key.startswith("pale text")})
PAIR_LABELS = [label for label in FIXTURE_LABELS if f"{label} | colour | back" in GOLDEN]
SINGLE_LABELS = [label for label in FIXTURE_LABELS if label not in PAIR_LABELS]
CHUNK = 6
PAIR_CHUNKS = [PAIR_LABELS[i : i + CHUNK] for i in range(0, len(PAIR_LABELS), CHUNK)]
SINGLE_CHUNKS = [SINGLE_LABELS[i : i + 2 * CHUNK] for i in range(0, len(SINGLE_LABELS), 2 * CHUNK)]
MEMORY_DPI = 300
MEMORY_PAGES = 12


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


def _png_files(folder: Path, scenes: list[Scene]) -> list[Path]:
    folder.mkdir()
    return [
        write_png(folder / f"page-{n:03d}.png", scene.image, dpi=scene.dpi)
        for n, scene in enumerate(scenes, start=1)
    ]


# ---- the verdicts are the golden table's --------------------------------------------------


def test_the_chunks_cover_every_fixture() -> None:
    assert sorted(label for chunk in PAIR_CHUNKS for label in chunk) == sorted(PAIR_LABELS)
    assert sorted(label for chunk in SINGLE_CHUNKS for label in chunk) == sorted(SINGLE_LABELS)
    assert len(PAIR_LABELS) >= 10
    assert len(SINGLE_LABELS) >= 25


@pytest.mark.parametrize("labels", PAIR_CHUNKS, ids=lambda chunk: f"{len(chunk)} sheets")
def test_the_two_sides_of_a_sheet_are_judged_as_the_golden_table_says(
    labels: list[str], tmp_path: Path, out: Path
) -> None:
    pairs = scene_pairs()
    scenes = [side for label in labels for side in pairs[label]]
    assert all(scene is not None for scene in scenes)
    draft = analyse_document(_png_files(tmp_path / "raw", scenes), settings(out))
    expected = [
        GOLDEN[f"{label} | colour | {side}"] for label in labels for side in ("front", "back")
    ]
    assert [page.blank for page in draft.pages] == expected
    assert [page.partner for page in draft.pages] == [
        number + 1 if number % 2 else number - 1 for number in range(1, len(scenes) + 1)
    ]


@pytest.mark.parametrize("labels", SINGLE_CHUNKS, ids=lambda chunk: f"{len(chunk)} pages")
def test_a_page_with_no_other_side_is_judged_as_the_golden_table_says(
    labels: list[str], tmp_path: Path, out: Path
) -> None:
    pairs = scene_pairs()
    files = _png_files(tmp_path / "raw", [pairs[label][0] for label in labels])
    draft = analyse_document(files, settings(out, duplex=False))
    assert [page.blank for page in draft.pages] == [
        GOLDEN[f"{label} | colour | front"] for label in labels
    ]
    assert {page.partner for page in draft.pages} == {None}


def test_the_golden_table_has_both_kinds_of_page_in_the_pairs() -> None:
    verdicts = {
        GOLDEN[f"{label} | colour | {side}"] for label in PAIR_LABELS for side in ("front", "back")
    }
    assert verdicts == {True, False}


# ---- what the draft says about each page --------------------------------------------------


def test_the_draft_describes_the_files_and_the_trim(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2), text_scene(3)])
    draft = analyse_document(pages, settings(out))
    assert draft.raw_dir == raw
    assert (draft.duplex, draft.keep_blank) == (True, False)
    assert [page.number for page in draft.pages] == [1, 2, 3]
    assert [page.name for page in draft.pages] == ["page-01.png", "page-02.png", "page-03.png"]
    assert [page.partner for page in draft.pages] == [2, 1, None]
    for page, path in zip(draft.pages, pages, strict=True):
        info = path.stat()
        assert (page.size, page.mtime_ns) == (info.st_size, info.st_mtime_ns)
        trimmed = trim_page(load_page(path))
        assert page.dpi == trimmed.page.dpi
        assert page.trim == TrimBox.from_trimmed(trimmed)
    assert draft.dropped == (2,)
    assert [page.number for page in draft.kept] == [1, 3]


def test_a_simplex_document_has_no_partners(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2)])
    draft = analyse_document(pages, settings(out, duplex=False))
    assert [page.partner for page in draft.pages] == [None, None]
    assert draft.dropped == (2,)


def test_kept_pages_carry_their_encoded_bytes_and_dropped_ones_do_not(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2)])
    draft = analyse_document(pages, settings(out))
    trimmed = trim_page(load_page(pages[0]))
    assert draft.pages[0].encoded == encode_page(trimmed.page, settings(out).colour)
    assert draft.pages[1].encoded is None


def test_without_encoding_no_page_carries_bytes(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2)])
    draft = analyse_document(pages, settings(out), encode=False)
    assert [page.encoded for page in draft.pages] == [None, None]
    assert draft.dropped == (2,)


def test_keep_blank_keeps_the_verdict_and_the_page(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [text_scene(1), blank_scene(2)])
    draft = analyse_document(pages, settings(out, keep_blank=True))
    assert [page.blank for page in draft.pages] == [False, True]
    assert draft.dropped == ()
    assert draft.pages[1].encoded is not None
    assert draft.keep_blank


def test_a_document_of_blank_pages_is_a_draft_not_an_error(raw: Path, out: Path) -> None:
    pages = write_pages(raw, [blank_scene(1), blank_scene(2)])
    draft = analyse_document(pages, settings(out))
    assert draft.dropped == (1, 2)
    assert draft.kept == ()


def test_pages_in_two_folders_have_no_raw_folder(tmp_path: Path, out: Path) -> None:
    first = write_pages(tmp_path / "one", [text_scene(1)])
    second = write_pages(tmp_path / "two", [text_scene(2)])
    assert analyse_document([*first, *second], settings(out)).raw_dir is None


def test_analysing_changes_nothing_in_the_output_folder(raw: Path, out: Path) -> None:
    analyse_document(write_pages(raw, [text_scene(1), blank_scene(2)]), settings(out))
    assert list(out.iterdir()) == []


# ---- refused before any work, as the build does ---------------------------------------------


def test_no_pages_is_an_error(out: Path) -> None:
    with pytest.raises(DocumentError, match="no pages"):
        analyse_document([], settings(out))


def test_an_unusable_page_stops_the_analysis_before_any_page_is_decoded(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = write_pages(raw, [text_scene(1), text_scene(2)])
    pages[1].write_bytes(b"not a png")
    counter = LiveCounter()
    monkeypatch.setattr(analyse_module, "load_page", counter)
    with pytest.raises(UnsupportedPageError, match=r"page-02\.png"):
        analyse_document(pages, settings(out))
    assert counter.loads == 0


def test_settings_that_cannot_make_a_pdf_are_refused_first(raw: Path, tmp_path: Path) -> None:
    pages = write_pages(raw, [text_scene(1)])
    with pytest.raises(DocumentError, match="not an existing folder"):
        analyse_document(pages, settings(tmp_path / "missing"))


# ---- the hooks ----------------------------------------------------------------------------


def test_on_page_is_called_once_per_page_in_order_blank_pages_included(
    raw: Path, out: Path
) -> None:
    calls: list[tuple[int, int]] = []
    pages = write_pages(raw, [text_scene(1), blank_scene(2), text_scene(3)])
    analyse_document(
        pages, settings(out), on_page=lambda number, total: calls.append((number, total))
    )
    assert calls == [(1, 3), (2, 3), (3, 3)]


@pytest.mark.parametrize("stop_at", [1, 2, 3, 4, 5])
def test_a_cancel_stops_before_the_next_page_is_processed(
    stop_at: int, raw: Path, out: Path
) -> None:
    cancel = threading.Event()
    seen: list[int] = []

    def on_page(number: int, total: int) -> None:
        seen.append(number)
        if number == stop_at:
            cancel.set()

    pages = write_pages(raw, [text_scene(n) for n in range(1, 6)])
    with pytest.raises(DocumentCancelledError):
        analyse_document(pages, settings(out), cancel=cancel, on_page=on_page)
    assert seen == list(range(1, stop_at + 1))


def test_a_cancel_that_is_already_set_loads_no_page(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counter = LiveCounter()
    monkeypatch.setattr(analyse_module, "load_page", counter)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DocumentCancelledError):
        analyse_document(write_pages(raw, [text_scene(1)]), settings(out), cancel=cancel)
    assert counter.loads == 0


# ---- memory: a sheet at a time ----------------------------------------------------------------


def _big_pages(raw: Path) -> list[Path]:
    scenes = [
        text_scene(n, dpi=MEMORY_DPI, paper_mm=SMALL_MM)
        if n % 3
        else paper_scene(dpi=MEMORY_DPI, paper_mm=SMALL_MM, seed=n)
        for n in range(MEMORY_PAGES)
    ]
    return _png_files(raw, scenes)


def test_a_duplex_document_never_holds_more_than_a_sheet_of_decoded_pages(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counter = LiveCounter()
    monkeypatch.setattr(analyse_module, "load_page", counter)
    draft = analyse_document(_big_pages(raw), settings(out))
    assert len(draft.pages) == MEMORY_PAGES
    assert counter.loads == MEMORY_PAGES
    assert counter.peak == 2


def test_a_simplex_document_never_holds_more_than_one_decoded_page(
    raw: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counter = LiveCounter()
    monkeypatch.setattr(analyse_module, "load_page", counter)
    analyse_document(_big_pages(raw), settings(out, duplex=False))
    assert counter.loads == MEMORY_PAGES
    assert counter.peak == 1


def test_the_draft_keeps_bytes_not_pixels(raw: Path, out: Path) -> None:
    draft = analyse_document(_big_pages(raw), settings(out))
    for page in draft.pages:
        assert page.encoded is None or isinstance(page.encoded.data, bytes)
    assert not any(
        isinstance(value, np.ndarray) for page in draft.pages for value in vars(page).values()
    )
