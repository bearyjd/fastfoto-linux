"""Whole-page saving of a failed sheet: what is kept from a photo, and what the user is told."""

import gc
import logging
import os
import threading
import weakref
from datetime import datetime
from pathlib import Path

import pytest
from PIL import ExifTags, Image

from fastfoto_linux.pipeline import unprocessed
from fastfoto_linux.pipeline.issues import SheetIssue, failed_sheet_line
from fastfoto_linux.pipeline.process import process_pages
from fastfoto_linux.pipeline.sides import BackPolicy, iter_photos
from tests.process_helpers import (
    DPI,
    WIDE,
    digitized_date,
    half_bright_front_sheet,
    jpeg_names,
    page_name,
    plain_sheet,
    save_page,
    settings_for,
    wide_sheet,
    workspace,
    write_sheets,
)
from tests.synth import make_frame

GENERIC_REASON = "the photo could not be processed"
DPI_REASON = "the two pages were scanned at different resolutions"
UNPROCESSED = "FastFoto_0002_unprocessed.jpg"


def quantization(path: Path) -> dict:
    with Image.open(path) as image:
        return dict(image.quantization)


def description(path: Path) -> str | None:
    with Image.open(path) as image:
        return image.getexif().get(ExifTags.Base.ImageDescription)


def three_sheets(tmp_path: Path) -> tuple[list[Path], Path]:
    raw, out = workspace(tmp_path)
    return write_sheets(raw, [plain_sheet(0), wide_sheet(1), plain_sheet(2)]), out


# --- what a photo has, a whole page has too --------------------------------------------------


@pytest.mark.parametrize(
    "error", [ValueError("odd"), RuntimeError("odd")], ids=["value", "runtime"]
)
def test_any_failure_to_save_a_sheet_whole_leaves_it_a_plain_failure(
    tmp_path, monkeypatch, error
) -> None:
    def explode(*args, **kwargs):
        raise error

    monkeypatch.setattr(unprocessed, "write_unprocessed", explode)
    pages, out = three_sheets(tmp_path)
    result = process_pages(pages, settings_for(out, back_policy=BackPolicy.NEVER))
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]
    assert result.photos == 2
    (issue,) = result.failed
    assert (issue.sheet, issue.saved) == (2, None)


def test_the_whole_page_has_the_jpeg_quality_of_a_photo(tmp_path) -> None:
    pages, out = three_sheets(tmp_path)
    process_pages(pages, settings_for(out, back_policy=BackPolicy.NEVER, quality=40))
    assert quantization(out / UNPROCESSED) == quantization(out / "FastFoto_0001.jpg")


def test_the_whole_page_carries_the_notes(tmp_path) -> None:
    pages, out = three_sheets(tmp_path)
    process_pages(pages, settings_for(out, back_policy=BackPolicy.NEVER, notes="Beach day"))
    assert description(out / UNPROCESSED) == "Beach day"


def test_the_scan_time_is_the_time_of_the_front_page(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    back_page, front_page = write_sheets(raw, [wide_sheet(0)])  # face-down: the back comes first
    front_time = datetime(2026, 10, 12, 9, 5, 7)
    os.utime(back_page, (datetime(2026, 10, 12, 9, 4, 0).timestamp(),) * 2)
    os.utime(front_page, (front_time.timestamp(),) * 2)
    process_pages([back_page, front_page], settings_for(out))
    assert digitized_date(out / "FastFoto_0001_unprocessed.jpg") == "2026:10:12 09:05:07"


@pytest.mark.parametrize(("front_first", "front_at"), [(True, 0), (False, 1)])
def test_the_declared_feed_order_decides_when_the_content_cannot(front_first, front_at) -> None:
    (front, _), (back, _) = half_bright_front_sheet()
    pages = [(back, DPI), (front, DPI)]  # a dark back and a front the paper score cannot separate
    assert unprocessed._front_at(pages, front_first) == front_at


# --- the reason is in plain words --------------------------------------------------------------


@pytest.mark.parametrize(
    "error", [ValueError("cannot cut this out"), RuntimeError("/home/x/page.png: boom")]
)
def test_an_unforeseen_failure_gets_a_generic_reason_and_the_details_go_to_the_log(
    tmp_path, monkeypatch, caplog, error
) -> None:
    def cannot_crop(*args, **kwargs):
        raise error

    monkeypatch.setattr("fastfoto_linux.pipeline.sides.crop", cannot_crop)
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0)])
    with caplog.at_level(logging.DEBUG, logger="fastfoto_linux.pipeline.unprocessed"):
        result = process_pages(pages, settings_for(out))
    (issue,) = result.failed
    assert issue.reason == GENERIC_REASON
    assert issue.saved is not None and issue.saved.unprocessed_reason == GENERIC_REASON
    details = [r for r in caplog.records if r.name == "fastfoto_linux.pipeline.unprocessed"]
    assert any(str(error) in r.getMessage() and r.levelno == logging.DEBUG for r in details)


def test_pages_scanned_at_different_resolutions_are_saved_with_a_plain_reason(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    (front, _), (back, _) = plain_sheet(0)
    pages = [save_page(raw, 1, back), save_page(raw, 2, front, dpi=2 * DPI)]
    result = process_pages(pages, settings_for(out))
    (issue,) = result.failed
    assert issue.reason == DPI_REASON
    assert issue.saved is not None


# --- one unreadable page does not lose the other -----------------------------------------------


@pytest.mark.parametrize(
    ("bad_page", "missing", "saved_name"),
    [(2, "back", "FastFoto_0002_unprocessed.jpg"), (3, "front", "FastFoto_0002_unprocessed.jpg")],
    ids=["back-unreadable", "front-unreadable"],
)
def test_the_readable_page_of_a_sheet_is_saved_whole_and_the_summary_names_the_missing_side(
    tmp_path, bad_page, missing, saved_name
) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1)], front_first=False)
    pages[bad_page].write_bytes(b"this is not a png")
    result = process_pages(pages, settings_for(out, back_policy=BackPolicy.ALWAYS))
    assert [n for n in jpeg_names(out) if "unprocessed" in n] == [saved_name]
    (issue,) = result.failed
    assert issue.sheet == 2
    assert issue.saved is not None and issue.saved.back is None
    assert f"the {missing} page" in issue.reason
    assert page_name(bad_page + 1) in issue.reason
    assert "could not be read" in issue.reason
    assert "identify" not in issue.reason  # nothing of the decoder's own wording
    assert issue.saved.unprocessed_reason == issue.reason


def test_a_sheet_whose_pages_are_both_unreadable_cannot_be_saved(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1)])
    for page in pages[2:]:
        page.write_bytes(b"this is not a png")
    result = process_pages(pages, settings_for(out, back_policy=BackPolicy.ALWAYS))
    assert [n for n in jpeg_names(out) if "unprocessed" in n] == []
    (issue,) = result.failed
    assert (issue.sheet, issue.saved) == (2, None)
    assert page_name(3) in issue.reason
    assert issue.save_failed is True


def test_a_sheet_that_could_not_be_saved_says_so() -> None:
    lost = SheetIssue(4, ("a.png", "b.png"), "the photo could not be processed", save_failed=True)
    line = failed_sheet_line(lost, 6)
    assert line.startswith("photo 4 of 6 fed")
    assert "saving the whole page failed too" in line
    plain = SheetIssue(4, ("a.png",), "odd page count")
    assert "saving" not in failed_sheet_line(plain, 6)


# --- memory: the failed sheet's images are gone before its pages are loaded again --------------


def test_the_images_of_a_failed_sheet_are_freed_before_the_error_is_handed_on() -> None:
    refs: list[weakref.ref] = []

    def loader(path: Path):
        frame = make_frame(dpi=75, side="front", **WIDE)[0]
        refs.append(weakref.ref(frame))
        return frame, 75

    alive_in_callback: list[int] = []
    gc.disable()  # only the explicit release may free them, not a sweep that happens to run
    try:
        batch = iter_photos(
            [Path("a.png"), Path("b.png")],
            duplex=True,
            loader=loader,
            on_sheet_error=lambda error: alive_in_callback.append(
                sum(ref() is not None for ref in refs)
            ),
        )
        assert list(batch) == []
    finally:
        gc.enable()
    assert alive_in_callback == [0]


# --- cancelling ---------------------------------------------------------------------------------


def test_a_cancel_that_comes_while_the_last_sheet_is_saved_whole_does_not_cancel_the_run(
    tmp_path,
) -> None:
    pages, out = three_sheets(tmp_path)
    cancel = threading.Event()

    def on_photo(files) -> None:
        if files.unprocessed_reason is not None:
            cancel.set()

    result = process_pages(
        pages[:4],
        settings_for(out, back_policy=BackPolicy.NEVER),
        on_photo=on_photo,
        cancel=cancel,
    )
    assert result.cancelled is False
    assert [issue.sheet for issue in result.failed] == [2]
    assert result.photos == 1
