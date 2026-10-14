"""A failing enhancer or orienter costs a sheet its enhanced copy, never the original."""

import logging

import numpy as np
import pytest

from fastfoto_linux.pipeline.process import process_pages
from tests.process_helpers import (
    LOGGER,
    invert,
    jpeg_names,
    jpeg_size,
    page_name,
    plain_sheet,
    settings_for,
    workspace,
    write_sheets,
)

THREE_SHEETS = [plain_sheet(0), plain_sheet(1), plain_sheet(2)]
SECOND_SHEET = (2, (page_name(3), page_name(4)))


def _failing_on_call(number: int, error: Exception, then=invert):
    """An enhancer or orienter that raises ``error`` on its ``number``-th call only."""
    calls: list[int] = []

    def func(img: np.ndarray, dpi: int) -> np.ndarray:
        calls.append(1)
        if len(calls) == number:
            raise error
        return then(img, dpi)

    return func


def test_a_failing_enhancer_still_writes_the_original_and_marks_the_sheet_degraded(
    tmp_path, caplog
) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, THREE_SHEETS)
    enhancer = _failing_on_call(2, ValueError("enhancer exploded"))
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        result = process_pages(pages, settings_for(out, enhancers=(enhancer,)))
    assert result.photos == 3
    assert result.failed == ()
    assert jpeg_names(out) == [
        "FastFoto_0001.jpg",
        "FastFoto_0001_a.jpg",
        "FastFoto_0002.jpg",
        "FastFoto_0003.jpg",
        "FastFoto_0003_a.jpg",
    ]
    (issue,) = result.degraded
    assert (issue.sheet, issue.pages) == SECOND_SHEET
    assert "enhancer exploded" in issue.reason
    assert "enhancer" in issue.reason
    assert not result.ok
    assert "enhancer exploded" in caplog.text


def test_a_failing_orienter_writes_the_original_unturned_and_skips_the_enhanced_copy(
    tmp_path,
) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, THREE_SHEETS)
    orienter = _failing_on_call(2, RuntimeError(), then=lambda img, dpi: np.rot90(img).copy())
    result = process_pages(pages, settings_for(out, orienter=orienter, enhancers=(invert,)))
    assert result.photos == 3
    assert result.failed == ()
    assert jpeg_names(out) == [
        "FastFoto_0001.jpg",
        "FastFoto_0001_a.jpg",
        "FastFoto_0002.jpg",
        "FastFoto_0003.jpg",
        "FastFoto_0003_a.jpg",
    ]
    widths = [jpeg_size(w.original) for w in result.written]
    assert [w < h for w, h in widths] == [True, False, True]  # the failed sheet stays landscape
    (issue,) = result.degraded
    assert (issue.sheet, issue.pages) == SECOND_SHEET
    assert "orienter" in issue.reason
    assert "RuntimeError" in issue.reason  # never an empty message


def test_a_failing_enhancer_with_enhanced_only_still_writes_the_original(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])
    enhancer = _failing_on_call(1, ValueError("enhancer exploded"))
    settings = settings_for(out, keep_original=False, enhancers=(enhancer,))
    result = process_pages(pages, settings)
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002_a.jpg"]
    assert [issue.sheet for issue in result.degraded] == [1]


def test_every_sheet_can_be_degraded_without_losing_a_photo(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), plain_sheet(1)])

    def broken(img: np.ndarray, dpi: int) -> np.ndarray:
        raise RuntimeError("no luck")

    result = process_pages(pages, settings_for(out, orienter=broken, enhancers=(invert,)))
    assert result.photos == 2
    assert [issue.sheet for issue in result.degraded] == [1, 2]
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]


def test_a_clean_run_is_ok(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])
    result = process_pages(pages, settings_for(out, enhancers=(invert,)))
    assert result.degraded == ()
    assert result.ok


def test_ctrl_c_in_the_orienter_is_not_swallowed(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet()])

    def interrupted(img: np.ndarray, dpi: int) -> np.ndarray:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        process_pages(pages, settings_for(out, orienter=interrupted))
