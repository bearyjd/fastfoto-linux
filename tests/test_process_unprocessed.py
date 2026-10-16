"""A sheet that cannot be turned into a photo is still saved whole, in sequence and reported."""

import errno
import os
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.output import PhotoDate, WrittenFiles, writer
from fastfoto_linux.pipeline.geometry import mm_to_px
from fastfoto_linux.pipeline.process import ProcessSettings, process_pages
from fastfoto_linux.pipeline.sides import BackPolicy
from tests.process_helpers import (
    DPI,
    NO_PHOTO_REASON,
    WIDE,
    digitized_date,
    jpeg_mean,
    jpeg_names,
    jpeg_size,
    original_date,
    page_name,
    plain_sheet,
    save_page,
    settings_for,
    wide_sheet,
    workspace,
    write_sheets,
)
from tests.synth import GREY_BAND_MM, make_frame

WHOLE_PAGE = "FastFoto_0002_unprocessed.jpg"
DARK_BELOW, WHITE_ABOVE = 150, 230  # mean grey of a dark textured front and of white paper
WORK_FACTOR = 2


def unprocessed(out: Path) -> list[str]:
    return [name for name in jpeg_names(out) if "unprocessed" in name]


def mean_of(out: Path, name: str) -> float:
    assert (out / name).exists(), f"{name} was not written"
    return jpeg_mean(out / name)


def tail_row() -> int:
    """The first row of the synthetic tail under a ``WIDE`` card."""
    top, height = WIDE["offset_mm"][1], WIDE["photo_mm"][1]
    return mm_to_px(top + height, DPI) + mm_to_px(GREY_BAND_MM, DPI)


def test_a_sheet_without_a_findable_photo_is_saved_whole_in_its_place(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1), plain_sheet(2)])
    result = process_pages(pages, settings_for(out, back_policy=BackPolicy.NEVER))
    assert jpeg_names(out) == ["FastFoto_0001.jpg", WHOLE_PAGE, "FastFoto_0003.jpg"]
    assert result.photos == 2
    assert result.sheets == 3
    assert result.ok is False
    (issue,) = result.failed
    assert (issue.sheet, issue.pages) == (2, (page_name(3), page_name(4)))
    assert issue.reason == NO_PHOTO_REASON
    assert issue.saved is not None
    assert issue.saved.original == out / WHOLE_PAGE
    assert issue.saved.unprocessed_reason == NO_PHOTO_REASON


@pytest.mark.parametrize("position", [0, 1, 2])
def test_the_numbers_follow_the_feed_order_wherever_the_bad_sheet_is(tmp_path, position) -> None:
    raw, out = workspace(tmp_path)
    sheets = [plain_sheet(n) for n in range(3)]
    sheets[position] = wide_sheet(9)
    result = process_pages(
        write_sheets(raw, sheets), settings_for(out, back_policy=BackPolicy.NEVER)
    )
    expected = [
        f"FastFoto_{n:04d}{'_unprocessed' if n == position + 1 else ''}.jpg" for n in range(1, 4)
    ]
    assert jpeg_names(out) == expected
    assert [issue.sheet for issue in result.failed] == [position + 1]


@pytest.mark.parametrize(
    ("policy", "back_saved"),
    [(BackPolicy.NEVER, False), (BackPolicy.AUTO, True), (BackPolicy.ALWAYS, True)],
)
def test_the_back_of_a_whole_page_follows_the_back_policy(tmp_path, policy, back_saved) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1)])
    process_pages(pages, settings_for(out, back_policy=policy))
    expected = [WHOLE_PAGE.replace(".jpg", "_b.jpg")] if back_saved else []
    assert [n for n in unprocessed(out) if n.endswith("_b.jpg")] == expected
    assert WHOLE_PAGE in unprocessed(out)


def test_the_whole_pages_are_jpegs_without_the_scanner_tail(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    result = process_pages(write_sheets(raw, [wide_sheet(0)]), settings_for(out))
    saved = result.failed[0].saved
    assert saved is not None
    assert saved.original is not None and saved.back is not None
    for path in (saved.original, saved.back):
        width, height = jpeg_size(path)
        assert width == mm_to_px(WIDE["photo_mm"][0], DPI)
        assert tail_row() <= height < tail_row() + WORK_FACTOR
        with Image.open(path) as image:
            assert image.format == "JPEG"


@pytest.mark.parametrize(
    ("expect_front_first", "front_page_first"),
    [(False, False), (True, True), (None, True)],
    ids=["face-down", "face-up", "unknown"],
)
def test_the_feed_order_tells_front_from_back_when_the_content_cannot(
    tmp_path, expect_front_first, front_page_first
) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [wide_sheet(0)], front_first=front_page_first)
    settings = settings_for(out, expect_front_first=expect_front_first)
    process_pages(pages, settings)
    assert mean_of(out, "FastFoto_0001_unprocessed.jpg") < DARK_BELOW
    assert mean_of(out, "FastFoto_0001_unprocessed_b.jpg") > WHITE_ABOVE


def test_the_normal_side_decision_is_used_when_it_works_for_the_sheet(
    tmp_path, monkeypatch
) -> None:
    def cannot_crop(*args, **kwargs):
        raise ValueError("cannot cut this out")

    monkeypatch.setattr("fastfoto_linux.pipeline.sides.crop", cannot_crop)
    raw, out = workspace(tmp_path)
    # Delivered face-up although the settings say face-down: the paper tells the sides apart.
    pages = write_sheets(raw, [plain_sheet(0)], front_first=True)
    result = process_pages(pages, settings_for(out, expect_front_first=False))
    assert result.failed[0].reason == "the photo could not be processed"
    assert mean_of(out, "FastFoto_0001_unprocessed.jpg") < DARK_BELOW
    assert mean_of(out, "FastFoto_0001_unprocessed_b.jpg") > WHITE_ABOVE


def test_the_whole_pages_carry_the_metadata_of_a_photo(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1)])
    scanned = datetime(2026, 10, 12, 9, 5, 7).timestamp()
    for page in pages[2:]:
        os.utime(page, (scanned, scanned))
    process_pages(pages, settings_for(out, album="Trip", date=PhotoDate(1975, 6, 14)))
    for name in ("Trip_0002_unprocessed.jpg", "Trip_0002_unprocessed_b.jpg"):
        assert original_date(out / "Trip" / name) == "1975:06:14 00:00:00"
        assert digitized_date(out / "Trip" / name) == "2026:10:12 09:05:07"


def test_on_photo_hears_the_whole_page_in_order(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1), plain_sheet(2)])
    heard: list[WrittenFiles] = []
    process_pages(pages, settings_for(out, back_policy=BackPolicy.NEVER), on_photo=heard.append)
    assert [files.index for files in heard] == [1, 2, 3]
    assert [files.unprocessed_reason for files in heard] == [None, NO_PHOTO_REASON, None]


def test_a_later_run_continues_after_the_whole_page_files(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    settings = settings_for(out, back_policy=BackPolicy.NEVER)
    process_pages(write_sheets(raw, [plain_sheet(0), wide_sheet(1)]), settings)
    later = write_sheets(tmp_path / "later", [plain_sheet(3)])
    process_pages(later, settings)
    assert jpeg_names(out) == ["FastFoto_0001.jpg", WHOLE_PAGE, "FastFoto_0003.jpg"]


def test_a_simplex_page_without_a_photo_is_saved_whole_without_a_back(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    raw.mkdir(exist_ok=True)
    good = save_page(raw, 1, make_frame(dpi=DPI, side="front", rng_seed=1)[0])
    wide = save_page(raw, 2, make_frame(dpi=DPI, side="front", rng_seed=2, **WIDE)[0])
    result = process_pages([good, wide], ProcessSettings(output_root=out, duplex=False))
    assert jpeg_names(out) == ["FastFoto_0001.jpg", WHOLE_PAGE]
    assert [(i.sheet, i.pages) for i in result.failed] == [(2, (page_name(2),))]
    assert result.sheets == 2


def test_a_lone_last_page_without_a_photo_is_saved_whole(tmp_path) -> None:
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0)])
    pages.append(save_page(raw, 3, make_frame(dpi=DPI, side="front", rng_seed=5, **WIDE)[0]))
    result = process_pages(pages, settings_for(out, back_policy=BackPolicy.ALWAYS))
    assert unprocessed(out) == [WHOLE_PAGE]
    assert result.sheets == 2


def test_a_failing_write_of_the_whole_pages_falls_back_to_listing_the_sheet(
    tmp_path, monkeypatch
) -> None:
    real = writer.write_new_files
    attempts: list[list[str]] = []

    def refuse_whole_pages(items):
        if any("unprocessed" in path.name for path, _ in items):
            attempts.append([path.name for path, _ in items])
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(items)

    monkeypatch.setattr(writer, "write_new_files", refuse_whole_pages)
    raw, out = workspace(tmp_path)
    pages = write_sheets(raw, [plain_sheet(0), wide_sheet(1), plain_sheet(2)])
    result = process_pages(pages, settings_for(out, back_policy=BackPolicy.NEVER))
    assert len(attempts) == 1
    assert jpeg_names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]
    assert result.photos == 2
    (issue,) = result.failed
    assert (issue.sheet, issue.saved) == (2, None)
    assert "no photo found" in issue.reason
    assert result.ok is False
