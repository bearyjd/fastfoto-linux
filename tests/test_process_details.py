"""``process_pages``: unchanged enhancements, scan dates from the page files, memory."""

import os
import weakref
from datetime import datetime
from pathlib import Path

import numpy as np

from fastfoto_linux.pipeline.process import process_pages
from fastfoto_linux.pipeline.sides import Photo
from tests.process_helpers import (
    DPI,
    digitized_date,
    invert,
    jpeg_names,
    plain_sheet,
    settings_for,
    workspace,
    write_sheets,
)


def test_an_enhancer_that_changes_nothing_writes_no_enhanced_copy(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    result = process_pages(pages, settings_for(out, enhancers=(lambda img, dpi: img,)))
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]
    assert result.enhanced == 0
    assert result.unchanged == 2
    assert result.ok


def test_a_chain_that_ends_where_it_started_is_unchanged_too(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    result = process_pages(pages, settings_for(out, enhancers=(invert, invert)))
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]
    assert result.unchanged == 1


def test_a_copy_with_identical_pixels_is_unchanged(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    result = process_pages(pages, settings_for(out, enhancers=(lambda img, dpi: img.copy(),)))
    assert result.unchanged == 1
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]


def test_only_the_sheets_that_changed_get_an_enhanced_copy(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    calls = []

    def second_only(img: np.ndarray, dpi: int) -> np.ndarray:
        calls.append(1)
        return img if len(calls) == 1 else invert(img, dpi)

    result = process_pages(pages, settings_for(out, enhancers=(second_only,)))
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg", "FastFoto_0002_a.jpg"]
    assert (result.enhanced, result.unchanged) == (1, 1)


def test_enhanced_only_still_writes_the_original_when_nothing_changed(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    settings = settings_for(out, keep_original=False, enhancers=(lambda img, dpi: img,))
    process_pages(pages, settings)
    assert jpeg_names(out) == ["FastFoto_0001.jpg"]


def _stamp(pages: list[Path], moment: datetime) -> None:
    for page in pages:
        os.utime(page, (moment.timestamp(), moment.timestamp()))


def test_the_scan_date_is_the_modification_time_of_the_page_files(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    _stamp(pages[:2], datetime(2001, 2, 3, 4, 5, 6))
    _stamp(pages[2:], datetime(2002, 3, 4, 5, 6, 7))
    first, second = process_pages(pages, settings_for(out)).written
    assert digitized_date(first.original) == "2001:02:03 04:05:06"
    assert digitized_date(second.original) == "2002:03:04 05:06:07"


def test_the_previous_photo_is_released_before_the_next_sheet_is_loaded(
    tmp_path, monkeypatch
) -> None:
    _, out = workspace(tmp_path)
    released: list[bool] = []

    def photos(pages, **kwargs):
        refs: list[weakref.ref[Photo]] = []
        for index in range(3):
            if refs:  # the consumer is asking for the next sheet
                released.append(refs[-1]() is None)
            photo = Photo(index, np.zeros((8, 8, 3), np.uint8), None, False, (Path("a.png"),), DPI)
            refs.append(weakref.ref(photo))
            yield photo
            del photo

    monkeypatch.setattr("fastfoto_linux.pipeline.process.iter_photos", photos)
    assert process_pages([], settings_for(out)).photos == 3
    assert released == [True, True]
