"""A band is bounded in pixels, not only in rows: a very wide page cannot make one band huge."""

import subprocess
import sys
import textwrap

import numpy as np
import pytest

from fastfoto_linux.documents import despeckle
from fastfoto_linux.documents.despeckle import DespeckleStatus, despeckle_white
from fastfoto_linux.documents.despeckle_tables import MAX_BAND_PIXELS, guard_px, speck_px

# A 512 x 30000 page of every other pixel black grew the process by 680 MiB at both 300 and
# 600 dpi when a band took every column of its 640 rows at once.
GROWTH_LIMIT_MIB = 300

CHILD = textwrap.dedent(
    """
    import resource, sys
    import cv2, numpy as np
    from fastfoto_linux.documents.despeckle import despeckle_white
    dpi, height, width, limit_mib = (int(v) for v in sys.argv[1:5])
    white = np.ones((height, width), dtype=bool)
    white[::2, ::2] = False
    cv2.setNumThreads(16)
    if limit_mib:
        with open("/proc/self/status") as status:
            size = int([l for l in status if l.startswith("VmSize")][0].split()[1]) * 1024
        cap = size + limit_mib * 2**20
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    try:
        result = despeckle_white(white, dpi)
    except BaseException as error:  # MemoryError or OpenCV's error
        print("ERR", type(error).__name__)
    else:
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(result.status.value, (after - before) // 1024)
    """
)


def run_child(dpi: int, height: int, width: int, limit_mib: int = 0) -> list[str]:
    done = subprocess.run(
        [sys.executable, "-c", CHILD, *(str(v) for v in (dpi, height, width, limit_mib))],
        capture_output=True,
        text=True,
        check=True,
        timeout=180,
    )
    return done.stdout.split()


@pytest.mark.parametrize("dpi", [300, 600])
def test_a_wide_dot_grid_stays_inside_its_memory_bound(dpi: int) -> None:
    status, growth = run_child(dpi, 512, 30000)
    assert status == "none"
    assert int(growth) < GROWTH_LIMIT_MIB, f"grew {growth} MiB"


def test_a_wide_page_completes_under_an_address_space_limit() -> None:
    assert run_child(600, 512, 30000, limit_mib=500)[0] == "none"


def test_a_page_too_wide_for_one_band_is_left_alone_not_allocated() -> None:
    assert run_child(600, 512, 100000, limit_mib=700) == [DespeckleStatus.TOO_LARGE.value, "0"]


def test_the_budget_is_six_million_pixels() -> None:
    assert MAX_BAND_PIXELS == 6_000_000


def window_px(dpi: int, width: int) -> int:
    return (1 + speck_px(dpi) + 2 * guard_px(dpi)) * width


def test_the_narrowest_band_decides_whether_a_page_is_too_wide() -> None:
    dpi = 600
    ok_width = MAX_BAND_PIXELS // window_px(dpi, 1)
    ok = np.ones((200, ok_width), dtype=bool)
    assert despeckle_white(ok, dpi).status is DespeckleStatus.NONE
    wide = np.ones((200, ok_width + 1), dtype=bool)
    result = despeckle_white(wide, dpi)
    assert (result.status, result.pixels, result.removed) == (DespeckleStatus.TOO_LARGE, None, 0)


def test_a_short_page_is_judged_by_its_own_height() -> None:
    dpi = 600  # 100 rows are fewer than the 128 of a full window
    short = np.ones((100, 50_000), dtype=bool)
    assert despeckle_white(short, dpi).status is DespeckleStatus.NONE


def shaped_page(seed: int, *, tall: bool) -> tuple[np.ndarray, int]:
    """A narrow tall page or a wide short one, with dot grids and specks."""
    rng = np.random.default_rng(seed)
    dpi = int(rng.choice([150, 300]))
    if tall:
        height, width = int(rng.integers(300, 500)), int(rng.integers(8, 40))
    else:
        height, width = int(rng.integers(20, 90)), int(rng.integers(600, 1500))
    page = np.ones((height, width), dtype=bool)
    page[:: int(rng.integers(2, 5)), :: int(rng.integers(2, 5))] = rng.random() < 0.3
    for _ in range(int(rng.integers(3, 25))):
        row, col = int(rng.integers(0, height - 2)), int(rng.integers(0, width - 2))
        page[row : row + int(rng.integers(1, 4)), col : col + int(rng.integers(1, 4))] = False
    return page, dpi


@pytest.mark.parametrize("tall", [True, False])
@pytest.mark.parametrize("multiple", [1, 2, 5])
@pytest.mark.parametrize("seed", range(15))
def test_any_band_budget_gives_the_same_pixels(
    monkeypatch: pytest.MonkeyPatch, tall: bool, multiple: int, seed: int
) -> None:
    white, dpi = shaped_page(seed, tall=tall)
    monkeypatch.setattr(despeckle, "BAND_ROWS", white.shape[0] + 10)
    monkeypatch.setattr(despeckle, "MAX_BAND_PIXELS", 10**9)
    whole = despeckle_white(white, dpi)
    budget = window_px(dpi, white.shape[1]) * multiple
    monkeypatch.setattr(despeckle, "MAX_BAND_PIXELS", budget)
    banded = despeckle_white(white, dpi)
    assert (banded.status, banded.removed) == (whole.status, whole.removed)
    assert (banded.pixels is None) == (whole.pixels is None)
    if whole.pixels is not None:
        assert np.array_equal(banded.pixels, whole.pixels)
