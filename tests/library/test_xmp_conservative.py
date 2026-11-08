"""A JPEG whose XMP might carry an Orientation, however spelled, is skipped, not turned.

The tiff namespace can be spelled with character references, entities and any prefix; a viewer's
XML parser resolves them, a byte scan does not. So any ``Orientation`` element or attribute, under
any prefix, counts, and so does a packet that is UTF-16 or too large to check.
"""

import struct
from pathlib import Path

import pytest

from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.jpeg_exif import set_orientation
from fastfoto_linux.library.plan import Action
from fastfoto_linux.library.xmp_scan import MAX_XMP_BYTES, names_any_orientation
from tests.library.jpeg_helpers import APP1, segment, write_file
from tests.library.untrusted_helpers import insert_after_jfif, sideways, with_xmp

REASON = "xmp-orientation"
EXTENSION_HEADER = b"http://ns.adobe.com/xmp/extension/\x00"
GUID = b"0123456789ABCDEF0123456789ABCDEF"
TIFF = "http://ns.adobe.com/tiff/1.0/"


def description(attributes: str, body: str = "") -> bytes:
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f"<rdf:Description {attributes}>{body}</rdf:Description></rdf:RDF></x:xmpmeta>"
    ).encode()


COMPETING = {
    "character reference in the namespace (reported bypass)": description(
        'xmlns:foo="http://ns.adobe.com/tiff/1.0&#x2f;" foo:Orientation="1"'
    ),
    "decimal reference in the namespace": description(
        'xmlns:foo="http://ns.adobe.com/tiff/1.0&#47;" foo:Orientation="1"'
    ),
    "entity in the namespace": description(
        'xmlns:foo="http://ns.adobe.com/tiff/1.0&s;" foo:Orientation="1"'
    ),
    "reference spelling a letter of the namespace": description(
        'xmlns:foo="http://ns.adobe.com/&#x74;iff/1.0/" foo:Orientation="1"'
    ),
    "alternate prefix, attribute": description(f'xmlns:q="{TIFF}" q:Orientation="6"'),
    "alternate prefix, element": description(
        f'xmlns:q="{TIFF}"', "<q:Orientation>6</q:Orientation>"
    ),
    "single quotes": description(f"xmlns:q='{TIFF}' q:Orientation='6'"),
    "double quotes": description(f'xmlns:q="{TIFF}" q:Orientation="6"'),
    "spaces around the equals sign": description(f'xmlns:q = "{TIFF}" q:Orientation = "6"'),
    "newline before the attribute": description(f'xmlns:q="{TIFF}"\n q:Orientation="6"'),
    "element, self-closing": description(f'xmlns:q="{TIFF}"', "<q:Orientation/>"),
    "element, newline before the end of the tag": description(
        "", "<q:Orientation\n>6</q:Orientation>"
    ),
    "element, no prefix": description(f'xmlns="{TIFF}"', "<Orientation>6</Orientation>"),
    "element, no prefix, default namespace by reference": description(
        'xmlns="http://ns.adobe.com/tiff/1.0&#x2f;"', "<Orientation>6</Orientation>"
    ),
    "namespace never bound": description('tiff:Orientation="6"'),
    "prefix that is not in the namespace table at all": description(
        "", "<zz:Orientation>6</zz:Orientation>"
    ),
    "non-ASCII prefix": description('xmlns:写真="urn:other" 写真:Orientation="6"'),
    "inside a comment": description("", "<!-- <q:Orientation>6</q:Orientation> -->"),
    "inside CDATA": description("", "<![CDATA[ <q:Orientation>6</q:Orientation> ]]>"),
    "attribute after a comment": description('a="<!--" q:Orientation="6"'),
    "upper case": description(f'xmlns:q="{TIFF}" q:ORIENTATION="6"'),
    "lower case": description(f'xmlns:q="{TIFF}" q:orientation="6"'),
    "mixed case element": description("", "<q:OrIeNtAtIoN>6</q:OrIeNtAtIoN>"),
    "utf-16 little endian": description(f'xmlns:q="{TIFF}" q:Orientation="6"')
    .decode()
    .encode("utf-16"),
    "utf-16 big endian": b"\xfe\xff"
    + description(f'xmlns:q="{TIFF}" q:Orientation="6"').decode().encode("utf-16-be"),
    "utf-16 without a byte order mark": description("", "<q:Orientation>6</q:Orientation>")
    .decode()
    .encode("utf-16-le"),
}

ORDINARY = {
    "title and creator tool": description(
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
        'xmp:CreatorTool="Scanner 1.0"',
        "<dc:title><rdf:Alt><rdf:li xml:lang='x-default'>Holiday</rdf:li></rdf:Alt></dc:title>",
    ),
    "tiff make and model": description(f'xmlns:tiff="{TIFF}" tiff:Make="Cam" tiff:Model="One"'),
    "word in a caption": description(
        'xmlns:dc="http://purl.org/dc/elements/1.1/" dc:description="Portrait Orientation"',
        "<dc:subject>Landscape Orientation</dc:subject>",
    ),
    "names that only start with the word": description(
        'x:OrientationNote="a"', "<x:Orientations/>"
    ),
}


def extended(chunk: bytes, offset: int, total: int) -> bytes:
    payload = EXTENSION_HEADER + GUID + struct.pack(">II", total, offset) + chunk
    return segment(APP1, payload)


def decided(tmp_path: Path, data: bytes) -> tuple[Action, str]:
    write_file(tmp_path, "a.jpg", data)
    row = decide_file(tmp_path, "a.jpg")
    return row.action, row.reason


@pytest.mark.parametrize("xmp", COMPETING.values(), ids=COMPETING.keys())
def test_a_possible_orientation_in_the_xmp_stops_the_turn(tmp_path: Path, xmp: bytes) -> None:
    assert decided(tmp_path, with_xmp(sideways(90), xmp)) == (Action.SKIP, REASON)


@pytest.mark.parametrize("xmp", COMPETING.values(), ids=COMPETING.keys())
def test_the_edit_itself_refuses_them(xmp: bytes) -> None:
    with pytest.raises(JpegExifError) as caught:
        set_orientation(with_xmp(sideways(90), xmp), 6)
    assert caught.value.reason == REASON


@pytest.mark.parametrize("xmp", COMPETING.values(), ids=COMPETING.keys())
def test_the_same_packet_as_extended_xmp_stops_the_turn(tmp_path: Path, xmp: bytes) -> None:
    data = insert_after_jfif(sideways(90), extended(xmp, 0, len(xmp)))
    assert decided(tmp_path, data) == (Action.SKIP, REASON)


@pytest.mark.parametrize("xmp", ORDINARY.values(), ids=ORDINARY.keys())
def test_ordinary_xmp_does_not_stop_the_turn(tmp_path: Path, xmp: bytes) -> None:
    for data in (
        with_xmp(sideways(90), xmp),
        insert_after_jfif(sideways(90), extended(xmp, 0, len(xmp))),
    ):
        assert decided(tmp_path, data)[0] is Action.ROTATE


def test_a_name_cut_in_two_by_an_extended_chunk_boundary_is_found(tmp_path: Path) -> None:
    whole = COMPETING["alternate prefix, attribute"]
    cut = whole.index(b"Orientation") + 4
    chunks = extended(whole[:cut], 0, len(whole)) + extended(whole[cut:], cut, len(whole))
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks)) == (Action.SKIP, REASON)


def test_chunks_that_overlap_stop_the_turn(tmp_path: Path) -> None:
    # A viewer that lets the second chunk overwrite the first reads ``q:Orientation=``; joined in
    # order the bytes read ``q:Orxxxxxxientation=``. Chunks that do not tile the packet are no
    # packet to trust.
    first = b"<d q:Orxxxxxxxx"
    second = b'ientation="6"/>'
    total = 8 + len(second)
    chunks = extended(first, 0, total) + extended(second, 8, total)
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks)) == (Action.SKIP, REASON)


def test_chunks_with_a_gap_stop_the_turn(tmp_path: Path) -> None:
    chunks = extended(b"<d/>", 0, 20) + extended(b"<e/>", 16, 20)
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks)) == (Action.SKIP, REASON)


def test_chunks_with_a_gap_that_the_declared_length_hides_stop_the_turn(tmp_path: Path) -> None:
    chunks = extended(b"<d/>", 0, 8) + extended(b"<e/>", 8 + 4, 8)
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks)) == (Action.SKIP, REASON)


def test_chunks_that_disagree_about_the_length_stop_the_turn(tmp_path: Path) -> None:
    chunks = extended(b"<d/>", 0, 8) + extended(b"<e/>", 4, 9)
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks)) == (Action.SKIP, REASON)


def test_chunks_that_tile_the_declared_length_exactly_do_not_stop_the_turn(tmp_path: Path) -> None:
    chunks = extended(b"<d/>", 0, 8) + extended(b"<e/>", 4, 8)
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks))[0] is Action.ROTATE


def test_chunks_that_do_not_add_up_to_the_declared_length_stop_the_turn(tmp_path: Path) -> None:
    chunks = extended(b"<d/>", 0, 99)
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks)) == (Action.SKIP, REASON)


def test_a_packet_of_extended_chunks_over_the_limit_stops_the_turn(tmp_path: Path) -> None:
    chunk = b" " * 60_000
    count = MAX_XMP_BYTES // len(chunk) + 2
    total = len(chunk) * count
    chunks = b"".join(extended(chunk, i * len(chunk), total) for i in range(count))
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks)) == (Action.SKIP, REASON)


def test_a_packet_over_the_limit_counts_without_being_scanned() -> None:
    assert names_any_orientation(b" " * (MAX_XMP_BYTES + 1))
    assert not names_any_orientation(b" " * MAX_XMP_BYTES)


def test_the_orientation_at_the_very_end_of_the_largest_packet_is_still_found() -> None:
    tail = b" q:Orientation="
    assert names_any_orientation(b" " * (MAX_XMP_BYTES - len(tail)) + tail)


def test_a_nul_byte_counts_wherever_it_is() -> None:
    assert names_any_orientation(b"<x:xmpmeta>\x00</x:xmpmeta>")
    assert not names_any_orientation(b"<x:xmpmeta></x:xmpmeta>")
