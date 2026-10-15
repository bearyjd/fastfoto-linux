"""An XMP orientation is found by its namespace and name, whatever prefix the packet gives it.

The tiff namespace can be bound to any prefix, and a large packet is split into Extended XMP
chunks; either way a viewer may still prefer that orientation to the Exif one.
"""

import struct
from pathlib import Path

import pytest

from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.jpeg_exif import set_orientation
from fastfoto_linux.library.plan import Action
from tests.library.jpeg_helpers import APP1, segment, write_file
from tests.library.untrusted_helpers import insert_after_jfif, sideways, with_xmp

REASON = "xmp-orientation"
EXTENSION_HEADER = b"http://ns.adobe.com/xmp/extension/\x00"
GUID = b"0123456789ABCDEF0123456789ABCDEF"
TIFF_NS = b'xmlns:t="http://ns.adobe.com/tiff/1.0/"'
RDF_NS = b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
OTHER_PREFIX_ATTRIBUTE = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF ' + RDF_NS + b"><rdf:Description "
    b"" + TIFF_NS + b' t:Orientation="6"/></rdf:RDF></x:xmpmeta>'
)
OTHER_PREFIX_ELEMENT = (
    b"<x:xmpmeta><rdf:RDF><rdf:Description " + TIFF_NS + b"><t:Orientation>8</t:Orientation>"
    b"</rdf:Description></rdf:RDF></x:xmpmeta>"
)
TIFF_WITHOUT_ORIENTATION = (
    b"<x:xmpmeta><rdf:RDF><rdf:Description " + TIFF_NS + b' t:Make="TestCam"/>'
    b"</rdf:RDF></x:xmpmeta>"
)
ORIENTATION_ELSEWHERE = (
    b'<x:xmpmeta><rdf:RDF><rdf:Description xmlns:ex="http://example.com/ns/" '
    b'ex:Orientation="portrait"/></rdf:RDF></x:xmpmeta>'
)


def extended(chunk: bytes, offset: int = 0, total: int | None = None) -> bytes:
    """An Extended XMP APP1 segment holding ``chunk``."""
    size = len(chunk) if total is None else total
    payload = EXTENSION_HEADER + GUID + struct.pack(">II", size, offset) + chunk
    return segment(APP1, payload)


def skipped_for_xmp(tmp_path: Path, data: bytes) -> bool:
    write_file(tmp_path, "a.jpg", data)
    row = decide_file(tmp_path, "a.jpg")
    return (row.action, row.reason) == (Action.SKIP, REASON)


@pytest.mark.parametrize(
    "packet", [OTHER_PREFIX_ATTRIBUTE, OTHER_PREFIX_ELEMENT], ids=["attribute", "element"]
)
def test_an_orientation_in_the_tiff_namespace_under_another_prefix_is_found(
    tmp_path: Path, packet: bytes
) -> None:
    assert skipped_for_xmp(tmp_path, with_xmp(sideways(90), packet))


@pytest.mark.parametrize(
    "packet", [OTHER_PREFIX_ATTRIBUTE, OTHER_PREFIX_ELEMENT], ids=["attribute", "element"]
)
def test_an_orientation_in_extended_xmp_is_found(tmp_path: Path, packet: bytes) -> None:
    data = insert_after_jfif(sideways(90), extended(packet))
    assert skipped_for_xmp(tmp_path, data)


CUTS = {
    "at a space": OTHER_PREFIX_ATTRIBUTE.index(b" t:Orientation"),
    "inside the name": OTHER_PREFIX_ATTRIBUTE.index(b"Orientation") + len(b"Orien"),
    "inside the namespace": OTHER_PREFIX_ATTRIBUTE.index(TIFF_NS)
    + len(b'xmlns:t="http://ns.adobe.com/ti'),
}


@pytest.mark.parametrize("in_order", [True, False], ids=["in order", "out of order"])
@pytest.mark.parametrize("cut", CUTS.values(), ids=CUTS.keys())
def test_an_orientation_split_across_extended_xmp_chunks_is_found(
    tmp_path: Path, cut: int, in_order: bool
) -> None:
    """The chunks hold the packet's bytes in turn (ordered by their offsets, which they carry);
    their own headers are not part of it, so a name cut in two is whole again once joined."""
    first, second = OTHER_PREFIX_ATTRIBUTE[:cut], OTHER_PREFIX_ATTRIBUTE[cut:]
    total = len(OTHER_PREFIX_ATTRIBUTE)
    parts = [extended(first, 0, total), extended(second, len(first), total)]
    chunks = b"".join(parts if in_order else parts[::-1])
    assert skipped_for_xmp(tmp_path, insert_after_jfif(sideways(90), chunks))


def test_chunks_of_different_packets_are_not_joined(tmp_path: Path) -> None:
    other_guid = b"F" * len(GUID)
    cut = CUTS["at a space"]  # the namespace is in one packet, the Orientation in the other
    first, second = OTHER_PREFIX_ATTRIBUTE[:cut], OTHER_PREFIX_ATTRIBUTE[cut:]
    foreign = segment(
        APP1,
        EXTENSION_HEADER + other_guid + struct.pack(">II", len(second), 0) + second,
    )
    chunks = extended(first, 0, len(OTHER_PREFIX_ATTRIBUTE)) + foreign
    write_file(tmp_path, "a.jpg", insert_after_jfif(sideways(90), chunks))
    assert decide_file(tmp_path, "a.jpg").action is Action.ROTATE


def test_the_edit_itself_refuses_these_files() -> None:
    for data in (
        with_xmp(sideways(90), OTHER_PREFIX_ATTRIBUTE),
        insert_after_jfif(sideways(90), extended(OTHER_PREFIX_ELEMENT)),
    ):
        with pytest.raises(JpegExifError) as caught:
            set_orientation(data, 6)
        assert caught.value.reason == REASON


@pytest.mark.parametrize(
    "packet", [TIFF_WITHOUT_ORIENTATION, ORIENTATION_ELSEWHERE], ids=["tiff-make", "other-name"]
)
def test_a_packet_without_an_xmp_orientation_does_not_stop_the_turn(
    tmp_path: Path, packet: bytes
) -> None:
    for data in (
        with_xmp(sideways(90), packet),
        insert_after_jfif(sideways(90), extended(packet)),
    ):
        write_file(tmp_path, "a.jpg", data)
        assert decide_file(tmp_path, "a.jpg").action is Action.ROTATE


def packet_with_prefix(prefix: str, namespace: bytes, *, element: bool) -> bytes:
    """A packet giving ``Orientation`` to ``prefix`` (UTF-8 in the bytes) bound to ``namespace``."""
    name = prefix.encode()
    description = b"<rdf:Description xmlns:" + name + b'="' + namespace + b'"'
    if element:
        body = description + b"><" + name + b":Orientation>6</" + name + b":Orientation>"
    else:
        body = description + b" " + name + b':Orientation="6">'
    return b"<x:xmpmeta><rdf:RDF>" + body + b"</rdf:Description></rdf:RDF></x:xmpmeta>"


NON_ASCII_PREFIXES = ["tïff", "写真", "é.1-ü"]  # NCName characters beyond ASCII


@pytest.mark.parametrize("element", [True, False], ids=["element", "attribute"])
@pytest.mark.parametrize("prefix", NON_ASCII_PREFIXES)
def test_a_non_ascii_prefix_bound_to_the_tiff_namespace_is_found(
    tmp_path: Path, prefix: str, element: bool
) -> None:
    packet = packet_with_prefix(prefix, b"http://ns.adobe.com/tiff/1.0/", element=element)
    assert skipped_for_xmp(tmp_path, with_xmp(sideways(90), packet))


@pytest.mark.parametrize("element", [True, False], ids=["element", "attribute"])
@pytest.mark.parametrize("prefix", NON_ASCII_PREFIXES)
def test_a_non_ascii_prefix_bound_to_another_namespace_is_not(
    tmp_path: Path, prefix: str, element: bool
) -> None:
    packet = packet_with_prefix(prefix, b"http://example.com/ns/", element=element)
    write_file(tmp_path, "a.jpg", with_xmp(sideways(90), packet))
    assert decide_file(tmp_path, "a.jpg").action is Action.ROTATE
