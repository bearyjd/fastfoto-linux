"""Structure-only checks on the private scans in ``test-scans/`` (never run in CI).

Assertions are on counts and millimetre sizes only: no pixel values, text or paths are ever put
into a failure message.
"""

from time import perf_counter

import pytest

from fastfoto_linux.pipeline.crop import crop, find_photo_box
from fastfoto_linux.pipeline.io import load_frame

pytestmark = pytest.mark.real_scans

PRINT_SIZES_MM = ((180.5, 128.5), (165.0, 103.0))  # 5x7" and the smaller print stock
SIZE_TOLERANCE_MM = 3.0
MAX_SECONDS_PER_FRAME = 2.0


def _matches_a_print_size(w_mm: float, h_mm: float) -> bool:
    return any(
        abs(w_mm - pw) <= SIZE_TOLERANCE_MM and abs(h_mm - ph) <= SIZE_TOLERANCE_MM
        for pw, ph in PRINT_SIZES_MM
    )


def test_every_real_page_yields_a_print_sized_box_quickly(real_scans_dir) -> None:
    pages = sorted(real_scans_dir.glob("photo-*.png"))
    assert len(pages) > 0, "no photo-*.png pages found"
    wrong: list[tuple[int, float, float]] = []
    slowest = 0.0
    for index, page in enumerate(pages):
        frame, dpi = load_frame(page)
        started = perf_counter()
        box = find_photo_box(frame, dpi)
        slowest = max(slowest, perf_counter() - started)
        _, _, w_mm, h_mm = box.mm(dpi)
        if not _matches_a_print_size(w_mm, h_mm):
            wrong.append((index, round(w_mm, 1), round(h_mm, 1)))
        assert crop(frame, box).shape == (box.h, box.w, 3)
    assert not wrong, (
        f"{len(wrong)} of {len(pages)} pages outside print sizes (index, w, h): {wrong}"
    )
    assert slowest < MAX_SECONDS_PER_FRAME, f"slowest find_photo_box took {slowest:.2f}s"
