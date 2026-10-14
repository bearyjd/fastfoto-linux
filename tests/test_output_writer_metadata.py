import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest
from PIL import ExifTags, Image

from fastfoto_linux import __version__
from fastfoto_linux.output import writer
from fastfoto_linux.output.metadata import DateRange, PhotoDate
from fastfoto_linux.output.writer import write_photo
from tests._output_helpers import DPI, HEIGHT, WIDTH, rgb

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


def xmp_of(path: Path) -> ET.Element:
    with Image.open(path) as image:
        return ET.fromstring(image.info["xmp"])


def test_exif_and_xmp_round_trip_through_the_written_jpeg(tmp_path: Path) -> None:
    result = write_photo(
        rgb(),
        dpi=DPI,
        output_root=tmp_path,
        album="Grandma 1970s",
        date=PhotoDate(1975, 6),
        notes="Beach day",
        scanned_at=SCANNED,
    )

    with Image.open(result.original) as image:
        exif = image.getexif()
        exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
    assert exif[ExifTags.Base.ImageDescription] == "Beach day"
    assert exif[ExifTags.Base.Software] == f"fastfoto-linux {__version__}"
    assert exif[ExifTags.Base.DateTime] == "2026:10:13 20:15:30"
    assert exif_ifd[ExifTags.Base.DateTimeOriginal] == "1975:06:01 00:00:00"
    assert exif_ifd[ExifTags.Base.DateTimeDigitized] == "2026:10:12 09:05:07"
    root = xmp_of(result.original)
    assert [e.text for e in root.findall(".//dc:subject/rdf:Bag/rdf:li", NS)] == ["Grandma 1970s"]
    assert [e.text for e in root.findall(".//dc:description/rdf:Alt/rdf:li", NS)] == ["Beach day"]
    assert [e.text for e in root.findall(".//photoshop:DateCreated", NS)] == ["1975-06"]


def test_every_file_of_a_photo_carries_the_same_metadata(tmp_path: Path) -> None:
    result = write_photo(
        rgb(),
        dpi=DPI,
        output_root=tmp_path,
        back=rgb(),
        enhanced=rgb(),
        album="Trip",
        date=PhotoDate(1975, 6, 14),
        notes="<Back & front> \u7956",
    )

    for path in result.paths:
        root = xmp_of(path)
        assert [e.text for e in root.findall(".//dc:description/rdf:Alt/rdf:li", NS)] == [
            "<Back & front> \u7956"
        ]
        assert [e.text for e in root.findall(".//photoshop:DateCreated", NS)] == ["1975-06-14"]
        with Image.open(path) as image:
            exif_ifd = image.getexif().get_ifd(ExifTags.IFD.Exif)
        assert exif_ifd[ExifTags.Base.DateTimeOriginal] == "1975:06:14 00:00:00"


def test_a_date_range_uses_its_start_for_exif(tmp_path: Path) -> None:
    result = write_photo(
        rgb(),
        dpi=DPI,
        output_root=tmp_path,
        date=DateRange(PhotoDate(1970), PhotoDate(1979)),
    )

    with Image.open(result.original) as image:
        exif_ifd = image.getexif().get_ifd(ExifTags.IFD.Exif)
    assert exif_ifd[ExifTags.Base.DateTimeOriginal] == "1970:01:01 00:00:00"


def test_without_a_date_there_is_no_original_date(tmp_path: Path) -> None:
    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path, album="Trip")

    with Image.open(result.original) as image:
        exif_ifd = image.getexif().get_ifd(ExifTags.IFD.Exif)
    assert ExifTags.Base.DateTimeOriginal not in exif_ifd
    assert xmp_of(result.original).findall(".//photoshop:DateCreated", NS) == []


def test_the_scan_time_defaults_to_the_write_time(tmp_path: Path) -> None:
    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path)

    with Image.open(result.original) as image:
        exif_ifd = image.getexif().get_ifd(ExifTags.IFD.Exif)
    assert exif_ifd[ExifTags.Base.DateTimeDigitized] == "2026:10:13 20:15:30"


def test_hostile_notes_and_album_cannot_break_the_files(tmp_path: Path) -> None:
    hostile = '<&"> \x00\x1b\ud800 </rdf:li><evil/> \u202e'

    result = write_photo(
        rgb(), dpi=DPI, output_root=tmp_path, album="Trip " + hostile, notes=hostile
    )

    with Image.open(result.original) as image:
        assert image.size == (WIDTH, HEIGHT)
    assert xmp_of(result.original).findall(".//evil") == []
