"""Whole-page saving of a failed sheet: what is kept from a photo, and what the user is told."""

import gc
import logging
import os
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
    LOGGER,
    WIDE,
    digitized_date,
    half_bright_front_sheet,
    jpeg_mean,
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
UNREADABLE_REASON = "a page of the sheet could not be read"
DARK_BELOW, WHITE_ABOVE = 150, 230  # mean grey of a dark textured front and of white paper
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
    ("front_first", "bad_page", "missing"),
    [(False, 2, "back"), (False, 3, "front"), (True, 2, "front"), (True, 3, "back")],
    ids=["down-back-bad", "down-front-bad", "up-front-bad", "up-back-bad"],
)
def test_the_readable_page_of_a_sheet_is_saved_whole_under_its_own_side_and_named(
    tmp_path, front_first, bad_page, missing
) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1)], front_first=front_first)
    pages[bad_page].write_bytes(b"this is not a png")
    settings = settings_for(out, back_policy=BackPolicy.ALWAYS, expect_front_first=front_first)
    result = process_pages(pages, settings)
    (issue,) = result.failed
    assert issue.sheet == 2
    assert issue.saved is not None
    lone_front = missing == "back"  # the front is what was read; else the back, keeping its _b
    name = "FastFoto_0002_unprocessed.jpg" if lone_front else "FastFoto_0002_unprocessed_b.jpg"
    saved = issue.saved
    assert [n for n in jpeg_names(out) if "unprocessed" in n] == [name]
    assert (saved.original, saved.back) == (
        (out / name, None) if lone_front else (None, out / name)
    )
    mean = jpeg_mean(out / name)  # the front of these sheets is dark, the back white
    assert mean < DARK_BELOW if lone_front else mean > WHITE_ABOVE
    assert f"the {missing} page" in issue.reason
    assert page_name(bad_page + 1) in issue.reason
    assert "could not be read" in issue.reason
    assert "identify" not in issue.reason  # nothing of the decoder's own wording
    assert issue.saved.unprocessed_reason == issue.reason


def test_a_lone_back_is_saved_even_when_backs_are_not_wanted(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1)], front_first=True)
    pages[2].write_bytes(b"this is not a png")  # the front: only the back is left of the sheet
    result = process_pages(
        pages, settings_for(out, back_policy=BackPolicy.NEVER, expect_front_first=True)
    )
    (issue,) = result.failed
    assert issue.saved is not None
    assert (issue.saved.original, issue.saved.back) == (
        None,
        out / "FastFoto_0002_unprocessed_b.jpg",
    )


def test_a_sheet_whose_pages_are_both_unreadable_cannot_be_saved(tmp_path, caplog) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1)])
    for page in pages[2:]:
        page.write_bytes(b"this is not a png")
    with caplog.at_level(logging.DEBUG):
        result = process_pages(pages, settings_for(out, back_policy=BackPolicy.ALWAYS))
    assert [n for n in jpeg_names(out) if "unprocessed" in n] == []
    (issue,) = result.failed
    assert (issue.sheet, issue.saved) == (2, None)
    assert issue.save_failed is True
    assert issue.reason == UNREADABLE_REASON
    assert issue.pages == (page_name(3), page_name(4))
    line = failed_sheet_line(issue, result.sheets)
    assert page_name(3) in line and UNREADABLE_REASON in line
    assert str(tmp_path) not in line  # no absolute path in what the user reads
    details = [r for r in caplog.records if r.name == LOGGER and r.levelno == logging.DEBUG]
    assert any(page_name(3) in r.getMessage() for r in details)  # the decoder's words go here


@pytest.mark.parametrize("error", [ValueError("finder broke"), RuntimeError("finder broke")])
def test_a_failure_of_the_photo_finder_is_not_called_an_unreadable_page(
    tmp_path, monkeypatch, error
) -> None:
    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr("fastfoto_linux.pipeline.sides.detect_photo", broken)
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0)])
    result = process_pages(pages, settings_for(out))
    (issue,) = result.failed
    assert issue.reason == GENERIC_REASON
    assert issue.saved is not None  # the pages could be read, so they are saved whole


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
