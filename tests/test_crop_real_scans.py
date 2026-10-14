"""Structure-only checks on the private scans in ``test-scans/`` (never run in CI).

Assertions are on counts and millimetre sizes only: no pixel values, text or paths are ever put
into a failure message. Frames are modified in memory only and never written anywhere.
"""

import logging
from time import perf_counter

import pytest

from fastfoto_linux.pipeline.crop import crop, detect_photo, find_photo_box
from fastfoto_linux.pipeline.io import load_frame
from tests.crop_helpers import CROP_LOGGER

pytestmark = pytest.mark.real_scans

PRINT_SIZES_MM = ((180.5, 128.5), (165.0, 103.0))  # 5x7" and the smaller print stock
SIZE_TOLERANCE_MM = 3.0
MAX_SECONDS_PER_FRAME = 2.0
DEFECT_ROW_AT = 0.85  # fraction of the frame height
DEFECT_WIDTH = 0.03  # fraction of the frame width


def _matches_a_print_size(w_mm: float, h_mm: float) -> bool:
    return any(
        abs(w_mm - pw) <= SIZE_TOLERANCE_MM and abs(h_mm - ph) <= SIZE_TOLERANCE_MM
        for pw, ph in PRINT_SIZES_MM
    )


def _pages(real_scans_dir):
    pages = sorted(real_scans_dir.glob("photo-*.png"))
    assert len(pages) > 0, "no photo-*.png pages found"
    return pages


def test_every_real_page_yields_a_print_sized_box_quickly(real_scans_dir, caplog) -> None:
    pages = _pages(real_scans_dir)
    wrong: list[tuple[int, float, float]] = []
    implausible = 0
    slowest = 0.0
    for index, page in enumerate(pages):
        frame, dpi = load_frame(page)
        started = perf_counter()
        with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
            detection = detect_photo(frame, dpi)
        slowest = max(slowest, perf_counter() - started)
        _, _, w_mm, h_mm = detection.box.mm(dpi)
        if not _matches_a_print_size(w_mm, h_mm):
            wrong.append((index, round(w_mm, 1), round(h_mm, 1)))
        implausible += not detection.plausible
        assert crop(frame, detection.box).shape == (detection.box.h, detection.box.w, 3)
    assert not wrong, (
        f"{len(wrong)} of {len(pages)} pages outside print sizes (index, w, h): {wrong}"
    )
    assert implausible == 0, f"{implausible} of {len(pages)} boxes flagged implausible"
    assert not caplog.records, f"{len(caplog.records)} warnings logged on real pages"
    assert slowest < MAX_SECONDS_PER_FRAME, f"slowest detect_photo took {slowest:.2f}s"


def test_one_defect_row_in_the_tail_does_not_change_any_real_box(real_scans_dir) -> None:
    pages = _pages(real_scans_dir)
    moved = []
    for index, page in enumerate(pages):
        frame, dpi = load_frame(page)
        baseline = find_photo_box(frame, dpi)
        row = int(frame.shape[0] * DEFECT_ROW_AT)
        frame[row, : int(frame.shape[1] * DEFECT_WIDTH)] = 128
        if find_photo_box(frame, dpi) != baseline:
            moved.append(index)
    assert not moved, f"defect row moved the box on {len(moved)} of {len(pages)} pages: {moved}"
