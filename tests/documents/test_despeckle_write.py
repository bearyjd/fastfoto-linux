"""Writing a document with despeckle: the draft's switch decides, cached bytes are checked."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from fastfoto_linux.documents import encode, write
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.draft_edit import rotate, set_crop
from fastfoto_linux.documents.encode import encode_page, render_page
from fastfoto_linux.documents.errors import DocumentCancelledError
from fastfoto_linux.documents.loader import WHITE, load_page
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy
from fastfoto_linux.documents.page_crop import PageCrop, edited_page
from fastfoto_linux.documents.write import write_document
from tests.doc_synth import write_png
from tests.documents import despeckle_fixtures as fx
from tests.documents.store_helpers import store_settings

CROP = PageCrop(1000, 2000, 7000, 9000)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def pages(tmp_path: Path) -> list[Path]:
    folder = tmp_path / "pages"
    folder.mkdir()
    pixels = np.where(fx.dust(), 255, 0).astype(np.uint8)
    return [write_png(folder / "page-0001.png", pixels, dpi=fx.DPI, mode="1")]


def settings_of(out: Path, policy: ColourPolicy = ColourPolicy.BW, **changes: Any):
    return store_settings(out, keep_blank=True, duplex=False, colour=policy, **changes)


class Spy:
    """The white pixels each ``encode._group4`` was given, and the calls of ``encode_page``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.whites: list[np.ndarray] = []
        self.encodes = 0
        group4, encode_page_ = encode._group4, write.encode_page

        def spy_group4(white: np.ndarray, dpi: int) -> bytes:
            self.whites.append(white.copy())
            return group4(white, dpi)

        def spy_encode(*args: Any, **kwargs: Any) -> Any:
            self.encodes += 1
            return encode_page_(*args, **kwargs)

        monkeypatch.setattr(encode, "_group4", spy_group4)
        monkeypatch.setattr(write, "encode_page", spy_encode)


def expected(draft: DocumentDraft, despeckle: bool) -> np.ndarray:
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))  # type: ignore[operator]
    edit = draft.edits.get(1, PageEdit())
    return render_page(edited_page(loaded, edit), ColourMode.BW, despeckle=despeckle) == WHITE


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
@pytest.mark.parametrize("cropped", [False, True])
def test_the_written_pixels_are_the_previewed_pixels(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch, turns: int, cropped: bool
) -> None:
    settings = settings_of(out)
    draft = replace(analyse_document(pages, settings, encode=False), despeckle=True)
    draft = rotate(draft, 1, turns)
    draft = set_crop(draft, 1, CROP if cropped else None)
    spy = Spy(monkeypatch)
    write_document(draft, settings)
    assert len(spy.whites) == 1
    assert np.array_equal(spy.whites[0], expected(draft, True))
    assert not np.array_equal(spy.whites[0], expected(draft, False))


def test_the_settings_are_never_read_at_write_time(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_of(out)
    draft = analyse_document(pages, settings, encode=False)
    spy = Spy(monkeypatch)
    write_document(draft, replace(settings, despeckle=True))
    write_document(replace(draft, despeckle=True), settings)
    assert np.array_equal(spy.whites[0], expected(draft, False))
    assert np.array_equal(spy.whites[1], expected(draft, True))


def carried(pages: list[Path], out: Path, *, despeckle: bool) -> DocumentDraft:
    """A draft whose page carries bytes made with ``despeckle``."""
    settings = settings_of(out)
    draft = analyse_document(pages, settings, encode=False)
    page = draft.pages[0]
    trimmed = page.trim.apply(load_page(pages[0], fallback_dpi=page.dpi))
    encoded = encode_page(trimmed, ColourMode.BW, despeckle=despeckle)
    return replace(draft, pages=(replace(page, encoded=encoded),))


def test_bytes_made_without_despeckle_are_not_reused_when_the_draft_says_true(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    write_document(replace(carried(pages, out, despeckle=False), despeckle=True), settings_of(out))
    assert spy.encodes == 1


def test_bytes_made_with_despeckle_are_not_reused_when_the_draft_says_false(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    write_document(carried(pages, out, despeckle=True), settings_of(out))
    assert spy.encodes == 1


@pytest.mark.parametrize("flag", [True, False])
def test_bytes_made_at_the_effective_value_are_reused(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch, flag: bool
) -> None:
    spy = Spy(monkeypatch)
    write_document(replace(carried(pages, out, despeckle=flag), despeckle=flag), settings_of(out))
    assert spy.encodes == 0


def test_a_grey_pages_cache_is_reused_with_despeckle_on(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "grey"
    folder.mkdir()
    grey = np.full((300, 200), 200, dtype=np.uint8)
    page = write_png(folder / "page-0001.png", grey, dpi=fx.DPI)
    settings = settings_of(out, ColourPolicy.GREY)
    draft = analyse_document([page], settings, encode=True)
    spy = Spy(monkeypatch)
    write_document(replace(draft, despeckle=True), settings)
    assert spy.encodes == 0


def test_a_cancel_during_the_despeckle_publishes_nothing(
    pages: list[Path], out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = encode.despeckle_white
    cancel = threading.Event()

    def trip(white: np.ndarray, dpi: int, **kwargs: Any) -> Any:
        cancel.set()
        return original(white, dpi, **kwargs)

    monkeypatch.setattr(encode, "despeckle_white", trip)
    settings = settings_of(out)
    draft = replace(analyse_document(pages, settings, encode=False), despeckle=True)
    with pytest.raises(DocumentCancelledError, match="despeckle cancelled"):
        write_document(draft, settings, cancel=cancel)
    assert list(out.iterdir()) == []
