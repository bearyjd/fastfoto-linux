"""Properties of despeckle on 200 seeded random pages (no hypothesis: a loop over seeds)."""

import threading

import cv2
import numpy as np
import pytest
from fastfoto_linux.documents.despeckle import DespeckleStatus, despeckle_white
from fastfoto_linux.documents.despeckle_tables import guard_px, speck_px

from fastfoto_linux.documents import despeckle
from fastfoto_linux.documents.errors import DocumentCancelledError
from tests.documents import despeckle_fixtures as fx

SEEDS = range(200)


def components(white: np.ndarray) -> tuple[int, np.ndarray, np.ndarray]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (~white).astype(np.uint8), connectivity=8, ltype=cv2.CV_32S
    )
    return count, labels, stats


@pytest.mark.parametrize("seed", SEEDS)
def test_the_properties_hold(seed: int) -> None:
    white, dpi = fx.random_page(seed)
    before = white.copy()
    result = despeckle_white(white, dpi)
    assert np.array_equal(white, before)  # the input is not modified
    again = despeckle_white(white, dpi)  # P5
    assert (again.status, again.removed) == (result.status, result.removed)
    assert (again.pixels is None) == (result.pixels is None)
    if result.pixels is not None:
        assert np.array_equal(again.pixels, result.pixels)
    out = white if result.pixels is None else result.pixels
    assert not (~out & white).any()  # P1: no ink appears
    s, g = speck_px(dpi), guard_px(dpi)
    count, labels, stats = components(white)
    survivors = np.bincount(labels[~out], minlength=count)
    for label in range(1, count):
        left, top, width, height, area = (int(v) for v in stats[label])
        assert survivors[label] in (0, area)  # P2: whole components only
        if width > s or height > s:
            assert survivors[label] == area  # never removed above the cap
        if survivors[label] == 0:  # P3
            assert result.status is DespeckleStatus.APPLIED
            window = ~out[max(0, top - g) : top + height + g, max(0, left - g) : left + width + g]
            assert not window.any()
    second = despeckle_white(out, dpi)  # P4
    if result.status is DespeckleStatus.APPLIED or result.status is DespeckleStatus.NONE:
        assert second.status is DespeckleStatus.NONE
    else:
        assert second.status is result.status
    assert second.pixels is None


def test_enough_random_pages_are_actually_despeckled() -> None:
    applied = sum(
        despeckle_white(*fx.random_page(seed)).status is DespeckleStatus.APPLIED
        for seed in range(0, 200, 5)
    )
    assert applied >= 5


@pytest.mark.parametrize("rows", [1, 7, 64, 513])
@pytest.mark.parametrize("seed", range(12))
def test_banded_equals_whole_page(monkeypatch: pytest.MonkeyPatch, rows: int, seed: int) -> None:
    white, dpi = fx.random_page(seed + 1000)
    monkeypatch.setattr(despeckle, "BAND_ROWS", white.shape[0] + 10)
    whole = despeckle_white(white, dpi)
    monkeypatch.setattr(despeckle, "BAND_ROWS", rows)
    banded = despeckle_white(white, dpi)
    assert (banded.status, banded.removed) == (whole.status, whole.removed)
    if whole.pixels is None:
        assert banded.pixels is None
    else:
        assert np.array_equal(banded.pixels, whole.pixels)


def test_a_cancel_before_the_second_band_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(despeckle, "BAND_ROWS", 100)

    class Stop(threading.Event):
        calls = 0

        def is_set(self) -> bool:
            self.calls += 1
            return self.calls >= 2

    white = fx.dust()
    before = white.copy()
    with pytest.raises(DocumentCancelledError):
        despeckle_white(white, fx.DPI, cancel=Stop())
    assert np.array_equal(white, before)
