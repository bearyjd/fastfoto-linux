"""Despeckle's memory is bounded by the band and the page, not by how many components a dense
pattern has; and a page too big at full resolution is left alone."""

import subprocess
import sys
import textwrap

import cv2
import numpy as np
import pytest

from fastfoto_linux.documents import despeckle
from fastfoto_linux.documents.despeckle import DespeckleStatus, despeckle_white
from fastfoto_linux.documents.despeckle_tables import MAX_DESPECKLE_PIXELS
from tests.documents import despeckle_fixtures as fx

# Peak resident growth allowed for a halftone A4 page. The runs measured about 45 MiB at 300 dpi
# and 110 MiB at 600 dpi; before the labelling was limited to one thread, 1.2 GiB and 2.3 GiB
# with 22 threads.
LIMITS_MIB = {300: 150, 600: 250}

CHILD = textwrap.dedent(
    """
    import resource, sys
    import cv2, numpy as np
    from fastfoto_linux.documents.despeckle import despeckle_white
    dpi = int(sys.argv[1])
    height, width = (3508, 2480) if dpi == 300 else (7016, 4960)
    white = np.ones((height, width), dtype=bool)
    white[::2, ::2] = False
    cv2.setNumThreads(16)  # as on a many-core machine, whatever the environment says
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = despeckle_white(white, dpi)
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(result.status.value, (after - before) // 1024)
    """
)


@pytest.mark.parametrize("dpi", [300, 600])
def test_a_halftone_page_stays_inside_its_memory_bound(dpi: int) -> None:
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(dpi)],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    status, growth = done.stdout.split()
    assert status == "none"  # nothing qualifies: the pattern is all one-pixel dots, but dense
    assert int(growth) < LIMITS_MIB[dpi], f"grew {growth} MiB"


def test_the_labelling_runs_on_one_thread_and_restores_the_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []
    original = cv2.connectedComponentsWithStats

    def spy(*args, **kwargs):
        seen.append(cv2.getNumThreads())
        return original(*args, **kwargs)

    monkeypatch.setattr(cv2, "connectedComponentsWithStats", spy)
    previous = cv2.getNumThreads()
    cv2.setNumThreads(4)
    try:
        despeckle_white(fx.dust(), fx.DPI)
        assert seen
        assert set(seen) == {1}
        assert cv2.getNumThreads() == 4
    finally:
        cv2.setNumThreads(previous)


def test_the_thread_count_is_restored_when_the_labelling_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("labelling failed")

    monkeypatch.setattr(cv2, "connectedComponentsWithStats", boom)
    previous = cv2.getNumThreads()
    cv2.setNumThreads(4)
    try:
        with pytest.raises(RuntimeError, match="labelling failed"):
            despeckle_white(fx.dust(), fx.DPI)
        assert cv2.getNumThreads() == 4
    finally:
        cv2.setNumThreads(previous)


def test_the_full_resolution_limit_is_80_million_pixels() -> None:
    assert MAX_DESPECKLE_PIXELS == 80_000_000  # A3 at 600 dpi is 69.6 million


def test_a_page_at_the_limit_is_despeckled_and_one_row_more_is_not() -> None:
    at_limit = np.ones((8000, 10000), dtype=bool)  # 80 million pixels, work grid 5 million
    at_limit[100:102, 100:102] = False
    result = despeckle_white(at_limit, 600)
    assert (result.status, result.removed) == (DespeckleStatus.APPLIED, 1)
    over = np.ones((8001, 10000), dtype=bool)
    over[100:102, 100:102] = False
    result = despeckle_white(over, 600)
    assert (result.status, result.pixels, result.removed) == (DespeckleStatus.TOO_LARGE, None, 0)


def test_the_limit_is_on_the_pixel_count_not_the_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(despeckle, "MAX_DESPECKLE_PIXELS", 600)
    tall = fx.blank(60, 10, 300)
    wide = fx.blank(10, 60, 300)
    over = fx.blank(61, 10, 300)
    assert despeckle_white(tall, 300).status is DespeckleStatus.NONE
    assert despeckle_white(wide, 300).status is DespeckleStatus.NONE
    assert despeckle_white(over, 300).status is DespeckleStatus.TOO_LARGE


@pytest.mark.parametrize("rows", [1, 2, 3, 16, 100])
@pytest.mark.parametrize("seed", range(20))
def test_dense_patterns_give_the_same_pixels_in_any_band_size(
    monkeypatch: pytest.MonkeyPatch, rows: int, seed: int
) -> None:
    white, dpi = fx.dense_page(seed)
    monkeypatch.setattr(despeckle, "BAND_ROWS", white.shape[0] + 10)
    whole = despeckle_white(white, dpi)
    monkeypatch.setattr(despeckle, "BAND_ROWS", rows)
    banded = despeckle_white(white, dpi)
    assert (banded.status, banded.removed) == (whole.status, whole.removed)
    assert (banded.pixels is None) == (whole.pixels is None)
    if whole.pixels is not None:
        assert np.array_equal(banded.pixels, whole.pixels)
