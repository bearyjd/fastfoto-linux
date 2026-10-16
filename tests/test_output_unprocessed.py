"""Whole-page files of a sheet that could not be processed: names, numbering, JPEG, metadata."""

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest
from PIL import ExifTags, Image

from fastfoto_linux.output import writer
from fastfoto_linux.output.metadata import PhotoDate
from fastfoto_linux.output.naming import next_index, unprocessed_paths
from fastfoto_linux.output.writer import write_photo, write_unprocessed
from tests._output_helpers import DPI, HEIGHT, WIDTH, names, rgb

REASON = "the photo's edges were not found (two items fed together?)"
SCANNED = datetime(2026, 10, 12, 9, 5, 7)
NOW = datetime(2026, 10, 13, 20, 15, 30)
NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(writer, "_now", lambda: NOW)


def touch(directory: Path, *file_names: str) -> None:
    for name in file_names:
        (directory / name).write_bytes(b"")


# --- names and numbering -----------------------------------------------------------------------


def test_the_whole_page_files_are_named_unprocessed_and_the_back_ends_in_b(tmp_path: Path) -> None:
    front, back = unprocessed_paths(tmp_path, "Trip", 4)
    assert front == tmp_path / "Trip_0004_unprocessed.jpg"
    assert back == tmp_path / "Trip_0004_unprocessed_b.jpg"


def test_next_index_counts_the_whole_page_names(tmp_path: Path) -> None:
    touch(tmp_path, "X_0003.jpg", "X_0004_unprocessed.jpg", "X_0004_unprocessed_b.jpg")
    assert next_index(tmp_path, "X") == 5


def test_next_index_counts_a_folder_holding_only_a_whole_page_back(tmp_path: Path) -> None:
    touch(tmp_path, "X_0007_unprocessed_b.JPG")
    assert next_index(tmp_path, "X") == 8


def test_next_index_still_ignores_other_letter_suffixes(tmp_path: Path) -> None:
    touch(tmp_path, "X_0072_ab.jpg", "X_0073_copy.jpg", "X_0074_unprocessed_bb.jpg")
    assert next_index(tmp_path, "X") == 1


# --- writing -----------------------------------------------------------------------------------


def test_a_sheet_is_written_in_sequence_with_its_back(tmp_path: Path) -> None:
    write_photo(rgb(), dpi=DPI, output_root=tmp_path)
    result = write_unprocessed(
        rgb(), dpi=DPI, output_root=tmp_path, back=rgb((30, 30, 200)), reason=REASON
    )
    write_photo(rgb(), dpi=DPI, output_root=tmp_path)
    assert names(tmp_path) == [
        "FastFoto_0001.jpg",
        "FastFoto_0002_unprocessed.jpg",
        "FastFoto_0002_unprocessed_b.jpg",
        "FastFoto_0003.jpg",
    ]
    assert result.index == 2
    assert result.original == tmp_path / "FastFoto_0002_unprocessed.jpg"
    assert result.enhanced is None
    assert result.back == tmp_path / "FastFoto_0002_unprocessed_b.jpg"
    assert result.unprocessed_reason == REASON


def test_without_a_back_only_the_front_is_written(tmp_path: Path) -> None:
    result = write_unprocessed(rgb(), dpi=DPI, output_root=tmp_path, reason=REASON)
    assert names(tmp_path) == ["FastFoto_0001_unprocessed.jpg"]
    assert result.back is None


def test_a_normal_photo_has_no_unprocessed_reason(tmp_path: Path) -> None:
    assert write_photo(rgb(), dpi=DPI, output_root=tmp_path).unprocessed_reason is None


def test_the_files_are_valid_jpegs_at_the_given_size_and_resolution(tmp_path: Path) -> None:
    result = write_unprocessed(rgb(), dpi=DPI, output_root=tmp_path, back=rgb(), reason=REASON)
    for path in result.paths:
        with Image.open(path) as image:
            assert image.format == "JPEG"
            assert image.size == (WIDTH, HEIGHT)
            assert tuple(round(v) for v in image.info["dpi"]) == (DPI, DPI)


def test_the_quality_is_honoured(tmp_path: Path) -> None:
    low = write_unprocessed(rgb(), dpi=DPI, output_root=tmp_path, quality=20, reason=REASON)
    high = write_unprocessed(rgb(), dpi=DPI, output_root=tmp_path, quality=95, reason=REASON)
    assert low.original is not None and high.original is not None
    assert low.original.stat().st_size < high.original.stat().st_size


def test_the_files_carry_the_date_and_album_metadata_of_a_photo(tmp_path: Path) -> None:
    result = write_unprocessed(
        rgb(),
        dpi=DPI,
        output_root=tmp_path,
        back=rgb(),
        album="Grandma 1970s",
        date=PhotoDate(1975, 6, 14),
        notes="Beach day",
        scanned_at=SCANNED,
        reason=REASON,
    )
    for path in result.paths:
        with Image.open(path) as image:
            exif = image.getexif()
            exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            root = ET.fromstring(image.info["xmp"])
        assert exif[ExifTags.Base.ImageDescription] == "Beach day"
        assert exif[ExifTags.Base.DateTime] == "2026:10:13 20:15:30"
        assert exif_ifd[ExifTags.Base.DateTimeOriginal] == "1975:06:14 00:00:00"
        assert exif_ifd[ExifTags.Base.DateTimeDigitized] == "2026:10:12 09:05:07"
        subject = [e.text for e in root.findall(".//dc:subject/rdf:Bag/rdf:li", NS)]
        assert subject == ["Grandma 1970s"]


def test_the_album_folder_and_prefix_are_used(tmp_path: Path) -> None:
    result = write_unprocessed(
        rgb(), dpi=DPI, output_root=tmp_path, album="Trip", prefix="Beach", reason=REASON
    )
    assert result.directory == tmp_path / "Trip"
    assert names(tmp_path / "Trip") == ["Beach_0001_unprocessed.jpg"]


def test_the_input_arrays_are_not_modified(tmp_path: Path) -> None:
    front, back = rgb(), rgb((1, 2, 3))  # read-only: a write by the writer would raise
    write_unprocessed(front, dpi=DPI, output_root=tmp_path, back=back, reason=REASON)


def test_an_existing_number_is_never_reused(tmp_path: Path) -> None:
    touch(tmp_path, "FastFoto_0009_unprocessed_b.jpg")
    result = write_unprocessed(rgb(), dpi=DPI, output_root=tmp_path, reason=REASON)
    assert result.index == 10
