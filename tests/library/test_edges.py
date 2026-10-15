"""Rare paths: odd JPEG layouts, failing writes, unusual plans and summaries."""

import logging
import shutil
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.library import apply as apply_module
from fastfoto_linux.library import decide as decide_module
from fastfoto_linux.library import jpeg_exif
from fastfoto_linux.library.apply import STATUS_FAILED, STATUS_STALE, apply_plan
from fastfoto_linux.library.decide import decide_files
from fastfoto_linux.library.jpeg_exif import JpegExifError, read_orientation, set_orientation
from fastfoto_linux.library.plan import PLAN_COLUMNS, Action, PlanRow, read_plan, write_plan
from fastfoto_linux.library.summary import CheckSummary, format_check
from fastfoto_linux.library.walk import WalkResult
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import (
    EXIF_HEADER,
    ORIENTATION,
    SOI,
    exif_bytes,
    make_jpeg,
    rotate_row,
    sideways_jpeg,
    write_file,
)
from tests.library.test_jpeg_exif import raw_exif_with_long_orientation, with_exif_segment

TIFF_SHORT = 3


def photo(tag: int | None = 6) -> bytes:
    return make_jpeg(load_astronaut(), exif=None if tag is None else exif_bytes(tag))


# --- odd JPEG layouts --------------------------------------------------------------------------


def test_fill_bytes_between_segments_are_skipped() -> None:
    data = photo()
    padded = SOI + b"\xff" + data[2:]
    assert read_orientation(padded) == 6
    assert read_orientation(set_orientation(padded, 3)) == 3


@pytest.mark.parametrize("cut", [b"\xff", b"\xff\xe0\x00"], ids=["after marker byte", "in header"])
def test_a_jpeg_cut_inside_a_segment_header_is_refused(cut: bytes) -> None:
    with pytest.raises(JpegExifError, match="ends"):
        read_orientation(SOI + cut)


def test_a_wrong_tiff_magic_is_refused() -> None:
    payload = EXIF_HEADER + b"II" + struct.pack("<HI", 43, 8) + bytes(4)
    with pytest.raises(JpegExifError, match="TIFF header"):
        read_orientation(with_exif_segment(photo(None), payload))


def test_an_orientation_entry_that_is_not_one_number_is_refused() -> None:
    entry = struct.pack(">HHI", ORIENTATION, TIFF_SHORT, 2) + struct.pack(">HH", 6, 6)
    payload = EXIF_HEADER + b"MM\x00*" + struct.pack(">IH", 8, 1) + entry + bytes(4)
    with pytest.raises(JpegExifError, match="single whole number"):
        read_orientation(with_exif_segment(photo(None), payload))


def test_a_parser_failure_while_rebuilding_is_a_clear_error(monkeypatch) -> None:
    def boom(self, data):
        raise ValueError("boom")

    monkeypatch.setattr(Image.Exif, "load", boom)
    data = with_exif_segment(photo(None), raw_exif_with_long_orientation(6))
    with pytest.raises(JpegExifError, match="cannot be rebuilt"):
        set_orientation(data, 8)


@pytest.mark.parametrize(
    ("broken", "message"),
    [(lambda data, at, order, tag: data, "confirmed"), (lambda *_: b"garbage", "re-read")],
    ids=["tag unchanged", "unreadable result"],
)
def test_a_result_that_does_not_check_out_is_never_returned(
    monkeypatch, broken, message: str
) -> None:
    monkeypatch.setattr(jpeg_exif, "_patched", broken)
    with pytest.raises(JpegExifError, match=message):
        set_orientation(photo(1), 6)


# --- apply: failing writes and unusable rows ------------------------------------------------


@pytest.fixture
def lib_and_dest(tmp_path: Path) -> tuple[Path, Path]:
    lib, dest = tmp_path / "lib", tmp_path / "dest"
    dest.mkdir()
    write_file(lib, "a.jpg", photo(1))
    return lib, dest


def test_a_row_without_tags_is_stale(lib_and_dest: tuple[Path, Path]) -> None:
    lib, dest = lib_and_dest
    row = rotate_row(lib, "a.jpg", 90, 1, 6)
    result = apply_plan([replace(row, new_tag=None)], lib, dest)
    assert [o.status for o in result.outcomes] == [STATUS_STALE]


def test_a_write_error_fails_that_row_and_leaves_no_file(
    monkeypatch, lib_and_dest: tuple[Path, Path]
) -> None:
    lib, dest = lib_and_dest

    def full_disk(items):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(apply_module, "write_new_files", full_disk)
    result = apply_plan([rotate_row(lib, "a.jpg", 90, 1, 6)], lib, dest)
    assert [(o.status, o.reason) for o in result.outcomes] == [(STATUS_FAILED, "io-error")]
    assert list(dest.iterdir()) == []


def test_a_failure_copying_times_removes_the_copy(
    monkeypatch, lib_and_dest: tuple[Path, Path]
) -> None:
    lib, dest = lib_and_dest

    def refuse(source, target):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(shutil, "copystat", refuse)
    result = apply_plan([rotate_row(lib, "a.jpg", 90, 1, 6)], lib, dest)
    assert [o.status for o in result.outcomes] == [STATUS_FAILED]
    assert list(dest.iterdir()) == []


# --- plan, workers, summary ------------------------------------------------------------------


def test_blank_lines_in_a_plan_are_ignored(tmp_path: Path) -> None:
    plan = tmp_path / "plan.csv"
    row = PlanRow("a.jpg", Action.KEEP, 0, 1, None, 0.0, "upright", 1, 2, "")
    write_plan(plan, (row,))
    text = plan.read_text(encoding="utf-8")
    header, body = text.split("\n", 1)
    plan.write_text(f"{header}\n\n{body}\n\n", encoding="utf-8")
    assert read_plan(plan, tmp_path) == (row,)
    assert header == ",".join(PLAN_COLUMNS)


def test_a_worker_call_gives_the_same_row_as_a_direct_one(tmp_path: Path) -> None:
    write_file(tmp_path, "a.jpg", sideways_jpeg(90, None))
    direct = decide_files(tmp_path, ["a.jpg"], jobs=1)[0]
    assert decide_module._decide_in_worker(str(tmp_path), "a.jpg") == direct


def test_fewer_than_one_job_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        decide_files(tmp_path, ["a.jpg"], jobs=0)


def test_progress_is_logged_while_workers_run(
    monkeypatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(decide_module, "PROGRESS_EVERY", 1)
    write_file(tmp_path, "a.jpg", b"x")
    write_file(tmp_path, "b.jpg", b"y")
    with caplog.at_level(logging.INFO, logger=decide_module.logger.name):
        decide_files(tmp_path, ["a.jpg", "b.jpg"], jobs=2)
    assert any("checked 2 of 2" in record.getMessage() for record in caplog.records)


def test_the_summary_mentions_links_and_unreadable_folders_only_when_there_are_some() -> None:
    summary = CheckSummary(0, 0, 3, 2, {90: 0, 180: 0, 270: 0}, 0, 0, {}, 0)
    text = format_check(summary, "plan.csv")
    assert "symlinks ignored: 3" in text
    assert "folders that could not be read: 2" in text
    quiet = format_check(CheckSummary(0, 0, 0, 0, {90: 0}, 0, 0, {}, 0), "plan.csv")
    assert "symlinks" not in quiet and "folders" not in quiet
    assert WalkResult((), 0, 0, 0).jpegs == ()
