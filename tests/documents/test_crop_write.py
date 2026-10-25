"""Writing a cropped page: the pixels are the preview's pixels, the cached bytes are not reused."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastfoto_linux.documents.page_crop import PageCrop, crop_box, edited_page

from fastfoto_linux.documents import analyse as analyse_module
from fastfoto_linux.documents import encode, write
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.draft_edit import rotate, set_crop
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy
from fastfoto_linux.documents.write import write_document
from tests.documents.crop_helpers import DPI, crop_draft, trimmed_size
from tests.documents.helpers import page_size_pt, reader
from tests.documents.store_helpers import store_settings

CROP = PageCrop(1000, 2000, 7000, 9000)
POLICY = {ColourMode.GREY: ColourPolicy.GREY, ColourMode.COLOUR: ColourPolicy.COLOUR}


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def settings_of(out: Path, kind: ColourMode):
    return store_settings(out, keep_blank=True, duplex=False, colour=POLICY[kind])


class Spy:
    """Records the pixels ``encode._jpeg`` was given and the calls of ``write.encode_page``."""

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


def preview_pixels(draft: DocumentDraft, kind: ColourMode, cleanup: CleanupPolicy) -> np.ndarray:
    """What the preview shows: load, trim, ``edited_page``, then ``render_page``."""
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))  # type: ignore[operator]
    edit = draft.edits.get(1, PageEdit())
    return render_page(edited_page(loaded, edit), kind, cleanup)


@pytest.mark.parametrize("cleanup", [CleanupPolicy.OFF, CleanupPolicy.LIGHT])
@pytest.mark.parametrize("kind", [ColourMode.GREY, ColourMode.COLOUR])
@pytest.mark.parametrize("turns", [0, 1, 2, 3])
@pytest.mark.parametrize("cropped", [False, True])
def test_the_written_pixels_are_the_previewed_pixels(
    tmp_path: Path,
    out: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup: CleanupPolicy,
    kind: ColourMode,
    turns: int,
    cropped: bool,
) -> None:
    draft = replace(crop_draft(tmp_path / "raw", kind), cleanup=cleanup)
    draft = rotate(draft, 1, turns)
    draft = set_crop(draft, 1, CROP if cropped else None)
    expected = preview_pixels(draft, kind, cleanup)
    spy = Spy(monkeypatch)
    write_document(draft, settings_of(out, kind))
    assert len(spy.jpegs) == 1
    assert np.array_equal(spy.jpegs[0], expected)


def test_a_cropped_page_is_smaller_than_the_page(tmp_path: Path, out: Path, monkeypatch) -> None:
    kind = ColourMode.GREY
    draft = set_crop(crop_draft(tmp_path / "raw", kind), 1, CROP)
    spy = Spy(monkeypatch)
    write_document(draft, settings_of(out, kind))
    width, height = trimmed_size(kind)
    left, top, right, bottom = crop_box(width, height, DPI, CROP)
    assert spy.jpegs[0].shape == (bottom - top, right - left)


def test_a_cropped_page_does_not_reuse_the_bytes_it_carries(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kind = ColourMode.GREY
    draft = crop_draft(tmp_path / "raw", kind, encoded=kind)
    spy = Spy(monkeypatch)
    calls: list[int] = []
    write_document(
        set_crop(draft, 1, CROP), settings_of(out, kind), on_page=lambda n, _: calls.append(n)
    )
    assert (spy.encodes, calls) == (1, [1])


def test_an_uncropped_page_still_reuses_the_bytes_it_carries(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kind = ColourMode.GREY
    draft = crop_draft(tmp_path / "raw", kind, encoded=kind)
    spy = Spy(monkeypatch)
    calls: list[int] = []
    write_document(draft, settings_of(out, kind), on_page=lambda n, _: calls.append(n))
    assert (spy.encodes, spy.jpegs, calls) == (0, [], [])


def test_clearing_the_crop_brings_the_cached_bytes_back(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kind = ColourMode.GREY
    draft = crop_draft(tmp_path / "raw", kind, encoded=kind)
    draft = set_crop(set_crop(draft, 1, CROP), 1, None)
    spy = Spy(monkeypatch)
    write_document(draft, settings_of(out, kind))
    assert spy.encodes == 0


@pytest.mark.parametrize("turns", [0, 1])
def test_the_pdf_page_is_as_big_as_the_crop(tmp_path: Path, out: Path, turns: int) -> None:
    kind = ColourMode.GREY
    draft = rotate(set_crop(crop_draft(tmp_path / "raw", kind), 1, CROP), 1, turns)
    result = write_document(draft, settings_of(out, kind))
    width, height = trimmed_size(kind)
    left, top, right, bottom = crop_box(width, height, DPI, CROP)
    size = ((right - left) * 72 / DPI, (bottom - top) * 72 / DPI)
    size = size[::-1] if turns else size
    assert page_size_pt(reader(result.pdf.read_bytes()), 0) == pytest.approx(size, abs=1)


def test_writing_never_analyses_again(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a crop must not be analysed again")

    monkeypatch.setattr(analyse_module, "analyse_document", refuse)
    kind = ColourMode.COLOUR
    write_document(set_crop(crop_draft(tmp_path / "raw", kind), 1, CROP), settings_of(out, kind))
