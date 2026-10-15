"""Only an Orientation in the tiff namespace stops a turn, not the word anywhere in the packet.

A caption that says "Portrait Orientation", or an ``Orientation`` property of some other
namespace, is no orientation a viewer would prefer to the Exif tag; ``tiff:Orientation`` (the usual
prefix), or the same property under whatever prefix is bound to the tiff namespace, is.
"""

import struct
from pathlib import Path

import pytest

from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.plan import Action
from tests.library.jpeg_helpers import APP1, segment, write_file
from tests.library.untrusted_helpers import insert_after_jfif, sideways, with_xmp

REASON = "xmp-orientation"
TIFF = b"http://ns.adobe.com/tiff/1.0/"
EXTENSION_HEADER = b"http://ns.adobe.com/xmp/extension/\x00"
GUID = b"0123456789ABCDEF0123456789ABCDEF"
DC = b'xmlns:dc="http://purl.org/dc/elements/1.1/"'
EX = b'xmlns:ex="http://example.com/ns/"'


def packet(attributes: bytes, children: bytes = b"") -> bytes:
    """An XMP packet with one description: its attributes and what is inside it."""
    return (
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
        + attributes
        + b">"
        + children
        + b"</rdf:Description></rdf:RDF></x:xmpmeta>"
    )


def tiff_ns(prefix: bytes) -> bytes:
    return b"xmlns:" + prefix + b'="' + TIFF + b'"'


# Packets that mention an Orientation without having one in the tiff namespace.
NOT_TIFF = {
    "caption attribute": packet(
        tiff_ns(b"tiff") + b" " + DC + b' tiff:Make="TestCam" dc:description="Portrait Orientation"'
    ),
    "caption element": packet(
        tiff_ns(b"tiff") + b" " + DC, b"<dc:description>Portrait Orientation</dc:description>"
    ),
    "another namespace": packet(
        tiff_ns(b"tiff") + b" " + EX + b' tiff:Make="TestCam" ex:Orientation="portrait"'
    ),
    "another namespace, prefix that ends like the tiff one": packet(
        tiff_ns(b"x") + b" " + EX + b' x:Make="TestCam" ex:Orientation="portrait"'
    ),
    "another namespace, element": packet(
        tiff_ns(b"t") + b" " + EX, b"<ex:Orientation>portrait</ex:Orientation>"
    ),
}

# Packets with an Orientation in the tiff namespace, whatever the prefix or the quotes.
TIFF_ORIENTATION = {
    "tiff attribute": packet(tiff_ns(b"tiff") + b' tiff:Orientation="6"'),
    "tiff element": packet(tiff_ns(b"tiff"), b"<tiff:Orientation>6</tiff:Orientation>"),
    "custom attribute": packet(tiff_ns(b"t") + b' t:Orientation="6"'),
    "custom element": packet(tiff_ns(b"t"), b"<t:Orientation>6</t:Orientation>"),
    "single quotes and spaces": packet(b"xmlns:t = '" + TIFF + b"' t:Orientation = '6'"),
    "bound after use": packet(b't:Orientation="6" ' + tiff_ns(b"t")),
    "next to another namespace": packet(
        EX + b" " + tiff_ns(b"t") + b' ex:Orientation="portrait" t:Orientation="6"'
    ),
    "default namespace element": packet(b'xmlns="' + TIFF + b'"', b"<Orientation>6</Orientation>"),
}


def decided(tmp_path: Path, data: bytes) -> tuple[Action, str]:
    write_file(tmp_path, "a.jpg", data)
    row = decide_file(tmp_path, "a.jpg")
    return row.action, row.reason


def extended(chunk: bytes, offset: int, total: int) -> bytes:
    payload = EXTENSION_HEADER + GUID + struct.pack(">II", total, offset) + chunk
    return segment(APP1, payload)


@pytest.mark.parametrize("xmp", NOT_TIFF.values(), ids=NOT_TIFF.keys())
def test_an_orientation_that_is_not_in_the_tiff_namespace_does_not_stop_the_turn(
    tmp_path: Path, xmp: bytes
) -> None:
    for data in (
        with_xmp(sideways(90), xmp),
        insert_after_jfif(sideways(90), extended(xmp, 0, len(xmp))),
    ):
        assert decided(tmp_path, data)[0] is Action.ROTATE


@pytest.mark.parametrize("xmp", TIFF_ORIENTATION.values(), ids=TIFF_ORIENTATION.keys())
def test_an_orientation_in_the_tiff_namespace_stops_the_turn(tmp_path: Path, xmp: bytes) -> None:
    assert decided(tmp_path, with_xmp(sideways(90), xmp)) == (Action.SKIP, REASON)


@pytest.mark.parametrize("cut_at", ["after the prefix", "inside the name"])
def test_a_tiff_orientation_split_across_extended_chunks_stops_the_turn(
    tmp_path: Path, cut_at: str
) -> None:
    whole = TIFF_ORIENTATION["custom attribute"]
    cut = whole.index(b"t:Orientation") + (2 if cut_at == "after the prefix" else len(b"t:Orie"))
    chunks = extended(whole[:cut], 0, len(whole)) + extended(whole[cut:], cut, len(whole))
    assert decided(tmp_path, insert_after_jfif(sideways(90), chunks)) == (Action.SKIP, REASON)
