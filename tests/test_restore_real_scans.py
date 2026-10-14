"""Structure-only checks on the private scans in ``test-scans/`` (never run in CI).

Only shapes, dtypes and timings are asserted: no pixel values, text or paths are ever put into a
failure message. The crop module is not available yet, so a fixed central region of each front
page (inside the photo on every front) stands in for the cropped photo.
"""

from pathlib import Path
from time import perf_counter

import cv2
import pytest

from fastfoto_linux.enhance.restore import restore_colour

pytestmark = pytest.mark.real_scans

DPI = 600
FRONT_PAGES = (2, 4, 6, 8)  # even-numbered pages are the fronts of the duplex pairs
REGION_ROWS = slice(300, 2400)
REGION_COLS = slice(1200, 3900)
MAX_SECONDS_PER_FRONT = 2.0


@pytest.mark.parametrize("page", FRONT_PAGES)
def test_restore_runs_quickly_on_real_fronts_and_keeps_shape_and_dtype(
    real_scans_dir: Path, page: int
) -> None:
    path = real_scans_dir / f"photo-{page:03d}.png"
    if not path.is_file():
        pytest.skip(f"front page {page} not present in the scans directory")
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert bgr is not None, f"front page {page} could not be decoded"
    height, width = bgr.shape[:2]
    if height < REGION_ROWS.stop or width < REGION_COLS.stop:
        pytest.skip(
            f"front page {page} is {width}x{height} px, smaller than the fixed "
            f"{REGION_COLS.stop}x{REGION_ROWS.stop} px region this test crops"
        )
    region = cv2.cvtColor(bgr[REGION_ROWS, REGION_COLS], cv2.COLOR_BGR2RGB)

    started = perf_counter()
    out = restore_colour(region, DPI)
    elapsed = perf_counter() - started

    assert out.shape == region.shape, f"page {page}: shape changed"
    assert out.dtype == region.dtype, f"page {page}: dtype changed"
    assert elapsed < MAX_SECONDS_PER_FRONT, f"page {page}: restore took {elapsed:.2f}s"
