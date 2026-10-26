"""Every path that can reach despeckle carries the cancel, and reports its status."""

import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from fastfoto_linux.documents import despeckle, encode
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.despeckle import DespeckleStatus
from fastfoto_linux.documents.encode import encode_page, render_page
from fastfoto_linux.documents.errors import DocumentCancelledError
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy
from tests.doc_synth import write_png
from tests.documents.store_helpers import store_settings

DPI = 300


@pytest.fixture
def page_file(tmp_path: Path) -> Path:
    """1200 rows x 1600 columns, white except one black pixel."""
    pixels = np.full((1200, 1600), 255, dtype=np.uint8)
    pixels[400, 400] = 0
    return write_png(tmp_path / "page-0001.png", pixels, dpi=DPI, mode="1")


def settings_of(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return store_settings(
        out, keep_blank=True, duplex=False, colour=ColourPolicy.BW, despeckle=True
    )


def count_bands(monkeypatch: pytest.MonkeyPatch, event: threading.Event | None) -> list[int]:
    """Spy on ``_band``; the first call sets ``event``. Eight bands make the page."""
    monkeypatch.setattr(despeckle, "BAND_ROWS", 150)
    calls: list[int] = []
    original = despeckle._band

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if event is not None:
            event.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(despeckle, "_band", spy)
    return calls


def test_encode_page_stops_after_the_first_band(monkeypatch: pytest.MonkeyPatch) -> None:
    event = threading.Event()
    calls = count_bands(monkeypatch, event)
    pixels = np.full((1200, 1600), 255, dtype=np.uint8)
    page = LoadedPage(pixels, ColourMode.BW, DPI)
    with pytest.raises(DocumentCancelledError, match="despeckle cancelled"):
        encode_page(page, ColourMode.BW, despeckle=True, cancel=event)
    assert len(calls) == 1


def test_a_cancel_reaches_despeckle_during_analysis(
    tmp_path: Path, page_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = threading.Event()
    calls = count_bands(monkeypatch, event)
    with pytest.raises(DocumentCancelledError, match="despeckle cancelled"):
        analyse_document([page_file], settings_of(tmp_path), cancel=event)
    assert len(calls) == 1


def test_a_cancel_from_on_page_still_lets_that_page_finish(
    tmp_path: Path, page_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = threading.Event()
    calls = count_bands(monkeypatch, None)
    draft = analyse_document(
        [page_file], settings_of(tmp_path), cancel=event, on_page=lambda *_: event.set()
    )
    assert len(calls) >= 8  # the page was encoded whole (every band of every round)
    assert draft.pages[0].encoded is not None
    assert draft.pages[0].encoded.despeckle is True


def test_the_status_is_reported_when_cleanup_succeeds() -> None:
    page = LoadedPage(np.full((600, 500), 230, dtype=np.uint8), ColourMode.GREY, DPI)
    seen: list[DespeckleStatus] = []
    cleaned: list[Any] = []
    render_page(
        page,
        ColourMode.GREY,
        CleanupPolicy.LIGHT,
        despeckle=True,
        on_cleanup=cleaned.append,
        on_despeckle=seen.append,
    )
    assert [status.value for status in cleaned] == ["applied"]  # cleanup returned early
    assert seen == [DespeckleStatus.NOT_BW]


def test_the_off_status_is_reported_when_cleanup_succeeds() -> None:
    page = LoadedPage(np.full((600, 500), 230, dtype=np.uint8), ColourMode.GREY, DPI)
    seen: list[DespeckleStatus] = []
    render_page(page, ColourMode.GREY, CleanupPolicy.LIGHT, on_despeckle=seen.append)
    assert seen == [DespeckleStatus.OFF]


def test_without_despeckle_a_cancel_mid_page_still_lets_cleanup_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing changes when despeckle is off: cleanup in analysis never saw the cancel."""
    page = write_png(tmp_path / "page-0001.png", np.full((600, 500), 230, dtype=np.uint8), dpi=DPI)
    out = tmp_path / "out"
    out.mkdir()
    settings = store_settings(
        out, keep_blank=True, duplex=False, colour=ColourPolicy.GREY, cleanup=CleanupPolicy.LIGHT
    )
    event = threading.Event()
    original = encode.clean_pixels

    def cancelled_mid_page(*args: Any, **kwargs: Any) -> Any:
        event.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(encode, "clean_pixels", cancelled_mid_page)
    draft = analyse_document([page], settings, cancel=event)
    assert draft.pages[0].encoded is not None
    assert draft.pages[0].encoded.cleanup is CleanupPolicy.LIGHT


def test_on_despeckle_is_not_called_when_the_cancel_stops_it() -> None:
    page = LoadedPage(np.full((300, 300), 255, dtype=np.uint8), ColourMode.BW, DPI)
    event = threading.Event()
    event.set()
    seen: list[DespeckleStatus] = []
    with pytest.raises(DocumentCancelledError):
        render_page(page, ColourMode.BW, despeckle=True, cancel=event, on_despeckle=seen.append)
    assert seen == []


def test_on_despeckle_is_not_called_when_despeckle_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("failed")

    monkeypatch.setattr(encode, "despeckle_white", boom)
    page = LoadedPage(np.full((300, 300), 255, dtype=np.uint8), ColourMode.BW, DPI)
    seen: list[DespeckleStatus] = []
    with pytest.raises(RuntimeError):
        render_page(page, ColourMode.BW, despeckle=True, on_despeckle=seen.append)
    assert seen == []
