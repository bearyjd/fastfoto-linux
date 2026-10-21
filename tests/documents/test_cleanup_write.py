"""Writing a document with paper cleanup: the draft's level decides, cached bytes are checked."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from fastfoto_linux.documents import cleanup as cleanup_module
from fastfoto_linux.documents import encode, write
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_edit import rotate, set_cleanup
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.errors import DocumentCancelledError
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy
from fastfoto_linux.documents.write import write_document
from tests.doc_synth import write_png
from tests.documents import cleanup_fixtures as fx
from tests.documents.store_helpers import store_settings

LIGHT, STRONG, OFF = CleanupPolicy.LIGHT, CleanupPolicy.STRONG, CleanupPolicy.OFF


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def pages(tmp_path: Path) -> list[Path]:
    folder = tmp_path / "pages"
    folder.mkdir()
    page = fx.odd_size_page(100, 400, 300).pixels
    page[300:330, 20:80] = (200, 30, 30)
    return [write_png(folder / "page-0001.png", page, dpi=100)]


def settings_of(out: Path, colour: ColourPolicy, **changes: Any):
    return store_settings(out, keep_blank=True, duplex=False, colour=colour, **changes)


class Spy:
    """Records the calls of ``write.encode_page`` and the pixels ``encode._jpeg`` was given."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.encodes = 0
        self.jpegs: list[np.ndarray] = []
        original_encode, original_jpeg = write.encode_page, encode._jpeg

        def encode_page(*args: Any, **kwargs: Any) -> Any:
            self.encodes += 1
            return original_encode(*args, **kwargs)

        def jpeg(pixels: np.ndarray, dpi: int) -> bytes:
            self.jpegs.append(pixels.copy())
            return original_jpeg(pixels, dpi)

        monkeypatch.setattr(write, "encode_page", encode_page)
        monkeypatch.setattr(encode, "_jpeg", jpeg)


def expected(draft: DocumentDraft, mode: ColourMode, policy: CleanupPolicy, turns: int):
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))  # type: ignore[operator]
    return render_page(write._turned(loaded, turns), mode, policy)


def test_bytes_made_with_cleanup_off_are_not_reused_for_a_draft_that_says_light(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_of(out, ColourPolicy.GREY)
    draft = analyse_document(pages, settings)
    assert draft.pages[0].encoded.cleanup is OFF  # type: ignore[union-attr]
    spy = Spy(monkeypatch)
    write_document(replace(draft, cleanup=LIGHT), settings)
    assert spy.encodes == 1
    assert np.array_equal(spy.jpegs[0], expected(draft, ColourMode.GREY, LIGHT, 0))
    assert not np.array_equal(spy.jpegs[0], expected(draft, ColourMode.GREY, OFF, 0))


def test_bytes_made_with_the_same_effective_level_are_reused(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_of(out, ColourPolicy.GREY, cleanup=LIGHT)
    draft = analyse_document(pages, settings)
    spy = Spy(monkeypatch)
    write_document(draft, settings)
    assert spy.encodes == 0 and spy.jpegs == []


def test_black_and_white_bytes_are_reused_whatever_the_level(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_of(out, ColourPolicy.BW)
    draft = analyse_document(pages, settings)
    spy = Spy(monkeypatch)
    write_document(replace(draft, cleanup=STRONG), settings)
    assert spy.encodes == 0


def test_a_page_override_decides_before_the_document(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_of(out, ColourPolicy.GREY)
    draft = analyse_document(pages, replace(settings, cleanup=LIGHT))
    kept_off = set_cleanup(draft, 1, OFF)
    spy = Spy(monkeypatch)
    write_document(kept_off, settings)
    assert spy.encodes == 1
    assert np.array_equal(spy.jpegs[0], expected(draft, ColourMode.GREY, OFF, 0))
    stronger = set_cleanup(replace(draft, cleanup=OFF), 1, STRONG)
    spy = Spy(monkeypatch)
    write_document(stronger, settings)
    assert np.array_equal(spy.jpegs[0], expected(draft, ColourMode.GREY, STRONG, 0))


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
@pytest.mark.parametrize("mode", [ColourMode.GREY, ColourMode.COLOUR])
def test_the_written_pixels_are_the_turned_page_cleaned(
    turns: int, mode: ColourMode, pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_of(out, ColourPolicy(mode.value))
    draft = analyse_document(pages, settings, encode=False)
    draft = rotate(replace(draft, cleanup=STRONG), 1, turns)
    spy = Spy(monkeypatch)
    write_document(draft, settings)
    assert np.array_equal(spy.jpegs[0], expected(draft, mode, STRONG, turns))


def test_the_turn_comes_before_the_cleanup(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_of(out, ColourPolicy.GREY)
    draft = rotate(replace(analyse_document(pages, settings, encode=False), cleanup=STRONG), 1, 1)
    spy = Spy(monkeypatch)
    write_document(draft, settings)
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))  # type: ignore[operator]
    after = np.ascontiguousarray(np.rot90(render_page(loaded, ColourMode.GREY, STRONG), -1))
    assert not np.array_equal(spy.jpegs[0], after)


def test_the_settings_level_is_never_read_at_write_time(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_of(out, ColourPolicy.GREY)
    draft = analyse_document(pages, settings, encode=False)
    spy = Spy(monkeypatch)
    write_document(draft, replace(settings, cleanup=STRONG))
    assert np.array_equal(spy.jpegs[0], expected(draft, ColourMode.GREY, OFF, 0))


def test_the_pdf_of_a_cleaned_page_differs_from_the_plain_one(pages: list[Path], out: Path) -> None:
    settings = settings_of(out, ColourPolicy.GREY)
    draft = analyse_document(pages, settings, encode=False)
    plain = write_document(draft, settings).pdf.read_bytes()
    cleaned = write_document(replace(draft, cleanup=STRONG), settings).pdf.read_bytes()
    assert plain != cleaned


class Trip(threading.Event):
    def __init__(self, calls: int) -> None:
        super().__init__()
        self.calls, self.seen = calls, 0

    def is_set(self) -> bool:
        self.seen += 1
        return self.seen > self.calls


def test_a_cancel_during_the_cleanup_publishes_nothing(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cleanup_module, "BAND_ROWS", 64)
    settings = settings_of(out, ColourPolicy.GREY)
    draft = replace(analyse_document(pages, settings, encode=False), cleanup=STRONG)
    cancel = Trip(3)  # the page check, then bands 1 and 2 of the first pass
    with pytest.raises(DocumentCancelledError, match="cleanup cancelled"):
        write_document(draft, settings, cancel=cancel)
    assert list(out.iterdir()) == []
    assert cancel.seen > 3
