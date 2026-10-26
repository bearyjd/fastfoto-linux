"""The switch: its default, its checks, where it counts and where it must do nothing."""

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastfoto_linux.documents.despeckle import DespeckleStatus

from fastfoto_linux.documents.bilevel import binarise
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_edit import set_document_despeckle
from fastfoto_linux.documents.encode import (
    effective_despeckle,
    encode_page,
    render_page,
)
from fastfoto_linux.documents.errors import DocumentEditError, DocumentSettingsError
from fastfoto_linux.documents.loader import WHITE, LoadedPage
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from fastfoto_linux.documents.settings import DocumentSettings, check_settings
from tests.documents import cleanup_fixtures as cfx
from tests.documents import despeckle_fixtures as fx
from tests.documents.edit_helpers import draft_of

BW, GREY, COLOUR = ColourMode.BW, ColourMode.GREY, ColourMode.COLOUR


def test_the_default_is_off(tmp_path: Path) -> None:
    assert DocumentSettings(output_root=tmp_path).despeckle is False
    assert draft_of(1).despeckle is False


@pytest.mark.parametrize("bad", [1, 0, "yes", None])
def test_settings_refuse_a_non_bool(tmp_path: Path, bad) -> None:
    settings = replace(DocumentSettings(output_root=tmp_path), despeckle=bad)
    with pytest.raises(DocumentSettingsError, match="despeckle must be true or false"):
        check_settings(settings)


def test_settings_accept_true(tmp_path: Path) -> None:
    check_settings(replace(DocumentSettings(output_root=tmp_path), despeckle=True))


def test_a_draft_refuses_a_non_bool() -> None:
    with pytest.raises(ValueError, match="despeckle"):
        replace(draft_of(1), despeckle=1)


def test_set_document_despeckle_is_pure_and_checked() -> None:
    draft = draft_of(2)
    on = set_document_despeckle(draft, True)
    assert isinstance(on, DocumentDraft)
    assert on.despeckle is True
    assert draft.despeckle is False
    assert set_document_despeckle(on, False).despeckle is False
    for bad in (1, "yes", None):
        with pytest.raises(DocumentEditError):
            set_document_despeckle(draft, bad)


@pytest.mark.parametrize(
    ("flag", "mode", "expected"),
    [(True, BW, True), (True, GREY, False), (True, COLOUR, False), (False, BW, False)],
)
def test_effective_despeckle(flag: bool, mode: ColourMode, expected: bool) -> None:
    assert effective_despeckle(flag, mode) is expected


def _colour_page() -> LoadedPage:
    return LoadedPage(cfx.shaded_paper().pixels, COLOUR, cfx.DPI)


@pytest.mark.parametrize("mode", [GREY, COLOUR])
def test_grey_and_colour_ignore_despeckle(mode: ColourMode) -> None:
    page = _colour_page()
    seen: list[DespeckleStatus] = []
    on = render_page(page, mode, despeckle=True, on_despeckle=seen.append)
    off = render_page(page, mode, despeckle=False)
    assert np.array_equal(on, off)
    assert seen == [DespeckleStatus.NOT_BW]
    quiet: list[DespeckleStatus] = []
    render_page(page, mode, despeckle=False, on_despeckle=quiet.append)
    assert quiet == [DespeckleStatus.OFF]


def test_off_is_the_render_of_main_for_every_mode() -> None:
    fixtures = [cfx.shaded_paper(), cfx.faint_pencil(), cfx.red_annotation(), cfx.punctuation_dot()]
    for fixture in fixtures:
        page = LoadedPage(fixture.pixels, COLOUR, fixture.dpi)
        grey = fixture.pixels.mean(axis=2).astype(np.uint8)
        for mode in (BW, GREY, COLOUR):
            plain = render_page(page, mode, CleanupPolicy.OFF)
            assert np.array_equal(plain, render_page(page, mode, despeckle=False))
        reference = np.where(binarise(_gray(page), page.dpi), WHITE, 0).astype(np.uint8)
        assert np.array_equal(render_page(page, BW, despeckle=False), reference)
        assert grey.shape == fixture.pixels.shape[:2]


def _gray(page: LoadedPage) -> np.ndarray:
    return cv2.cvtColor(page.pixels, cv2.COLOR_RGB2GRAY)


@pytest.mark.parametrize("kind", [BW, GREY, COLOUR])
def test_encode_page_bytes_are_unchanged_without_the_flag(kind: ColourMode) -> None:
    pixels = cfx.shaded_paper().pixels
    pixels = {COLOUR: pixels, GREY: pixels[..., 0], BW: np.where(pixels[..., 0] > 128, 255, 0)}[
        kind
    ]
    page = LoadedPage(np.ascontiguousarray(pixels, dtype=np.uint8), kind, cfx.DPI)
    for mode in (BW, GREY, COLOUR):
        plain = encode_page(page, mode)
        assert encode_page(page, mode, despeckle=False).data == plain.data
        assert plain.despeckle is False


def test_a_black_and_white_page_is_despeckled_and_recorded() -> None:
    white = fx.dust()
    page = LoadedPage(np.where(white, 255, 0).astype(np.uint8), BW, fx.DPI)
    seen: list[DespeckleStatus] = []
    out = render_page(page, BW, despeckle=True, on_despeckle=seen.append)
    assert (out == WHITE).all()
    assert seen == [DespeckleStatus.APPLIED]
    assert encode_page(page, BW, despeckle=True).despeckle is True
    assert encode_page(page, BW).data != encode_page(page, BW, despeckle=True).data


def test_a_binarised_colour_page_is_despeckled_with_its_chroma() -> None:
    white, source = fx.red_dot()
    grey = np.where(white, 235, 0).astype(np.uint8)
    rgb = np.stack([grey] * 3, axis=2)
    rgb[500:503, 500:503] = (220, 30, 30)
    page = LoadedPage(rgb, COLOUR, fx.DPI)
    plain = render_page(page, BW, despeckle=False)
    out = render_page(page, BW, despeckle=True)
    assert (plain[500:503, 500:503] == 0).all()
    assert (out[500:503, 500:503] == 0).all()  # the red dot stays
    assert (plain[900:903, 900:903] == 0).all()
    assert (out[900:903, 900:903] == WHITE).all()  # the grey speck goes
    assert source.shape[:2] == plain.shape
