import xml.etree.ElementTree as ET
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from PIL import ExifTags, Image

from fastfoto_linux import __version__
from fastfoto_linux.output.errors import InvalidDateError, InvalidNotesError
from fastfoto_linux.output.metadata import (
    MAX_NOTES_CHARS,
    DateRange,
    PhotoDate,
    PhotoMetadata,
    build_exif,
    build_xmp,
)

NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SOFTWARE = f"fastfoto-linux {__version__}"
SCANNED = datetime(2026, 10, 12, 9, 5, 7)
WRITTEN = datetime(2026, 10, 13, 20, 15, 30)
APP1_LIMIT = 65_000


def make_meta(**overrides: object) -> PhotoMetadata:
    fields: dict[str, object] = {
        "scanned_at": SCANNED,
        "written_at": WRITTEN,
        "album": "Grandma 1970s",
        "notes": "Beach day",
        "date": PhotoDate(1975, 6, 14),
    }
    fields.update(overrides)
    return PhotoMetadata(**fields)  # type: ignore[arg-type]


def read_exif(meta: PhotoMetadata) -> tuple[Image.Exif, dict[int, object]]:
    exif = Image.Exif()
    exif.load(build_exif(meta))
    return exif, dict(exif.get_ifd(ExifTags.IFD.Exif))


def read_xmp(meta: PhotoMetadata) -> ET.Element:
    return ET.fromstring(build_xmp(meta))


def texts(root: ET.Element, path: str) -> list[str | None]:
    return [element.text for element in root.findall(path, NS)]


# --- PhotoDate / DateRange ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1975", PhotoDate(1975)),
        ("1975-06", PhotoDate(1975, 6)),
        ("1975-06-14", PhotoDate(1975, 6, 14)),
        (" 1975-06 ", PhotoDate(1975, 6)),
        ("1976-02-29", PhotoDate(1976, 2, 29)),
        ("0999", PhotoDate(999)),
    ],
)
def test_photo_date_parse_good(text: str, expected: PhotoDate) -> None:
    assert PhotoDate.parse(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "75",
        "1975-13",
        "1975-00",
        "1975-02-30",
        "1975-02-29",
        "1975-06-00",
        "1975-06-32",
        "1975-6",
        "1975-06-1",
        "1975/06",
        "19750",
        "abc",
        "0000",
        "1975-06-14T10:00",
        "1975-",
        "\u0661\u0669\u0667\u0665",
    ],
)
def test_photo_date_parse_bad(text: str) -> None:
    with pytest.raises(InvalidDateError):
        PhotoDate.parse(text)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"year": 0}, "year"),
        ({"year": 10000}, "year"),
        ({"year": 1975, "month": 13}, "month"),
        ({"year": 1975, "day": 3}, "month"),
        ({"year": 1975, "month": 2, "day": 30}, "day"),
    ],
)
def test_photo_date_validates_on_construction(fields: dict[str, int], message: str) -> None:
    with pytest.raises(InvalidDateError, match=message):
        PhotoDate(**fields)


def test_photo_date_is_frozen() -> None:
    date = PhotoDate(1975)

    with pytest.raises(FrozenInstanceError):
        date.year = 1980  # type: ignore[misc]


@pytest.mark.parametrize(
    ("date", "iso", "exif"),
    [
        (PhotoDate(1975), "1975", "1975:01:01 00:00:00"),
        (PhotoDate(1975, 6), "1975-06", "1975:06:01 00:00:00"),
        (PhotoDate(1975, 6, 14), "1975-06-14", "1975:06:14 00:00:00"),
        (PhotoDate(999), "0999", "0999:01:01 00:00:00"),
    ],
)
def test_photo_date_formats(date: PhotoDate, iso: str, exif: str) -> None:
    assert str(date) == iso
    assert date.exif_datetime == exif


def test_date_range_parse_and_format() -> None:
    parsed = DateRange.parse("1975-06/1975-08-15")

    assert parsed == DateRange(PhotoDate(1975, 6), PhotoDate(1975, 8, 15))
    assert str(parsed) == "1975-06/1975-08-15"


def test_date_range_allows_a_single_point_in_time() -> None:
    assert str(DateRange.parse("1975/1975")) == "1975/1975"


@pytest.mark.parametrize(
    "text", ["", "1975", "1975/", "/1975", "1979/1970", "1975-06/1975-05", "a/b"]
)
def test_date_range_rejects_malformed_or_reversed_ranges(text: str) -> None:
    with pytest.raises(InvalidDateError):
        DateRange.parse(text)


@pytest.mark.parametrize(
    "text",
    ["1975-06/1975", "1975-06-14/1975-06", "1970-03/1970", "1975-06-14/1975", "1975/1975-12-31"],
)
def test_date_range_accepts_a_coarse_end_that_covers_the_start(text: str) -> None:
    assert str(DateRange.parse(text)) == text


@pytest.mark.parametrize(
    "text", ["1975-06/1975-05", "1975-06-14/1975-06-13", "1975-07/1975-06-30", "1976/1975-12-31"]
)
def test_date_range_rejects_an_end_that_falls_before_the_start(text: str) -> None:
    with pytest.raises(InvalidDateError, match="before"):
        DateRange.parse(text)


def test_date_range_rejects_reversed_construction() -> None:
    with pytest.raises(InvalidDateError, match="before"):
        DateRange(PhotoDate(1980), PhotoDate(1970))


# --- EXIF --------------------------------------------------------------------------------------


def test_exif_carries_notes_software_and_the_three_timestamps() -> None:
    exif, exif_ifd = read_exif(make_meta())

    assert exif[ExifTags.Base.ImageDescription] == "Beach day"
    assert exif[ExifTags.Base.Software] == SOFTWARE
    assert exif[ExifTags.Base.DateTime] == "2026:10:13 20:15:30"
    assert exif_ifd[ExifTags.Base.DateTimeOriginal] == "1975:06:14 00:00:00"
    assert exif_ifd[ExifTags.Base.DateTimeDigitized] == "2026:10:12 09:05:07"


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        (PhotoDate(1975), "1975:01:01 00:00:00"),
        (PhotoDate(1975, 6), "1975:06:01 00:00:00"),
        (DateRange(PhotoDate(1970, 3), PhotoDate(1979)), "1970:03:01 00:00:00"),
    ],
)
def test_exif_original_date_is_filled_to_the_start_of_the_period(
    date: PhotoDate | DateRange, expected: str
) -> None:
    _, exif_ifd = read_exif(make_meta(date=date))

    assert exif_ifd[ExifTags.Base.DateTimeOriginal] == expected


def test_exif_without_a_date_or_notes_omits_those_tags() -> None:
    exif, exif_ifd = read_exif(make_meta(date=None, notes=None))

    assert ExifTags.Base.ImageDescription not in exif
    assert ExifTags.Base.DateTimeOriginal not in exif_ifd
    assert exif_ifd[ExifTags.Base.DateTimeDigitized] == "2026:10:12 09:05:07"
    assert exif[ExifTags.Base.Software] == SOFTWARE


def test_exif_description_is_written_when_the_notes_are_printable_ascii() -> None:
    exif, _ = read_exif(make_meta(notes="Beach day, 1975: a/b & (c)"))

    assert exif[ExifTags.Base.ImageDescription] == "Beach day, 1975: a/b & (c)"


@pytest.mark.parametrize(
    "notes",
    [
        "Caf\u00e9",
        "\u00bd cup of sugar",
        "na\u00efve \u7956\u6bcd",
        "\u7956\u6bcd\U0001f600",
        "a\x00b",
        "line1\nline2",
        "tab\there",
    ],
)
def test_exif_description_is_omitted_unless_the_notes_are_already_printable_ascii(
    notes: str,
) -> None:
    exif, _ = read_exif(make_meta(notes=notes))

    assert ExifTags.Base.ImageDescription not in exif


def test_notes_that_are_not_printable_ascii_stay_complete_in_xmp() -> None:
    notes = "\u00bd cup of sugar \u7956\u6bcd\nsecond line"

    root = read_xmp(make_meta(notes=notes))

    assert texts(root, ".//dc:description/rdf:Alt/rdf:li") == [notes]


def test_exif_timestamps_convert_aware_datetimes_to_local_time() -> None:
    aware = datetime(2026, 1, 2, 12, 30, 45, tzinfo=UTC)

    exif, exif_ifd = read_exif(make_meta(scanned_at=aware, written_at=aware))

    expected = aware.astimezone().strftime("%Y:%m:%d %H:%M:%S")
    assert exif[ExifTags.Base.DateTime] == expected
    assert exif_ifd[ExifTags.Base.DateTimeDigitized] == expected


# --- XMP ---------------------------------------------------------------------------------------


def test_xmp_is_a_wrapped_xpacket() -> None:
    xmp = build_xmp(make_meta())

    assert xmp.startswith(b"<?xpacket begin=")
    assert xmp.rstrip().endswith(b'<?xpacket end="w"?>')
    assert len(xmp) < APP1_LIMIT


def test_xmp_carries_album_notes_date_and_creator_tool() -> None:
    root = read_xmp(make_meta())

    assert texts(root, ".//dc:subject/rdf:Bag/rdf:li") == ["Grandma 1970s"]
    assert texts(root, ".//dc:description/rdf:Alt/rdf:li") == ["Beach day"]
    description = root.find(".//dc:description/rdf:Alt/rdf:li", NS)
    assert description is not None
    assert description.attrib[XML_LANG] == "x-default"
    assert texts(root, ".//photoshop:DateCreated") == ["1975-06-14"]
    assert texts(root, ".//xmp:CreatorTool") == [SOFTWARE]


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        (PhotoDate(1975), "1975"),
        (PhotoDate(1975, 6), "1975-06"),
        (PhotoDate(1975, 6, 14), "1975-06-14"),
    ],
)
def test_xmp_date_keeps_the_precision_it_was_given(date: PhotoDate, expected: str) -> None:
    assert texts(read_xmp(make_meta(date=date)), ".//photoshop:DateCreated") == [expected]


def test_xmp_range_uses_its_start_as_date_created_and_records_the_whole_range() -> None:
    root = read_xmp(make_meta(date=DateRange(PhotoDate(1970), PhotoDate(1979, 12))))

    assert texts(root, ".//photoshop:DateCreated") == ["1970"]
    assert texts(root, ".//dc:coverage") == ["1970/1979-12"]


def test_xmp_omits_what_it_was_not_given() -> None:
    root = read_xmp(make_meta(album=None, notes=None, date=None))

    assert root.findall(".//dc:subject", NS) == []
    assert root.findall(".//dc:description", NS) == []
    assert root.findall(".//dc:coverage", NS) == []
    assert root.findall(".//photoshop:DateCreated", NS) == []
    assert texts(root, ".//xmp:CreatorTool") == [SOFTWARE]


@pytest.mark.parametrize(
    "notes",
    [
        "<&\">' ]]> <!-- x --> <?pi?>",
        "</rdf:li></rdf:Alt><evil/>",
        "Caf\u00e9 \u7956\u6bcd \U0001f600 \u202e",
        "line1\nline2\ttab",
        "&amp; &#0; &lt;",
    ],
)
def test_xmp_notes_round_trip_exactly_and_cannot_inject_markup(notes: str) -> None:
    root = read_xmp(make_meta(notes=notes))

    assert texts(root, ".//dc:description/rdf:Alt/rdf:li") == [notes]
    assert root.findall(".//evil") == []


def test_xmp_album_with_markup_characters_round_trips() -> None:
    album = 'Ben & Jerry\'s <1970s> "x" </rdf:li><evil/>'

    root = read_xmp(make_meta(album=album))

    assert texts(root, ".//dc:subject/rdf:Bag/rdf:li") == [album]
    assert root.findall(".//evil") == []


def test_xmp_replaces_characters_xml_cannot_hold() -> None:
    hostile = 'a\x00\x1b\ud800<&">b\x0b\x0c\ufffe\uffffc'

    root = read_xmp(make_meta(notes=hostile, album=hostile))

    expected = 'a\ufffd\ufffd\ufffd<&">b\ufffd\ufffd\ufffd\ufffdc'
    assert texts(root, ".//dc:description/rdf:Alt/rdf:li") == [expected]
    assert texts(root, ".//dc:subject/rdf:Bag/rdf:li") == [expected]


def test_xmp_normalises_line_endings() -> None:
    root = read_xmp(make_meta(notes="a\r\nb\rc"))

    assert texts(root, ".//dc:description/rdf:Alt/rdf:li") == ["a\nb\nc"]


def test_xmp_collapses_whitespace_in_the_album_name() -> None:
    root = read_xmp(make_meta(album="  Grandma \n 1970s "))

    assert texts(root, ".//dc:subject/rdf:Bag/rdf:li") == ["Grandma 1970s"]


@pytest.mark.parametrize("char", ["\U0001f600", "&", "<"])
def test_longest_allowed_notes_fit_in_one_jpeg_app1_segment(char: str) -> None:
    meta = make_meta(notes=char * MAX_NOTES_CHARS)

    assert len(build_xmp(meta)) < APP1_LIMIT
    assert len(build_exif(meta)) < APP1_LIMIT


def test_notes_over_the_limit_are_rejected() -> None:
    with pytest.raises(InvalidNotesError, match=str(MAX_NOTES_CHARS)):
        make_meta(notes="x" * (MAX_NOTES_CHARS + 1))


def test_building_xmp_leaves_the_global_xml_namespace_registry_alone() -> None:
    build_xmp(make_meta())

    element = ET.Element("{http://purl.org/dc/elements/1.1/}title")
    assert b"ns0:title" in ET.tostring(element)


def test_metadata_is_frozen() -> None:
    meta = make_meta()

    with pytest.raises(FrozenInstanceError):
        meta.notes = "changed"  # type: ignore[misc]
