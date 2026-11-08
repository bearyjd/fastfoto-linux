"""The shared XMP scan reads the markup (names, not values or text), and fails closed.

Round-1 review findings: a DTD can build or supply an Orientation, a non-UTF-8 declaration hides
one, a caption saying ``Orientation=portrait`` must not be mistaken for one, and Extended XMP
must not be joined before its size is checked. Each rule is tried on the scan itself and on the
JPEG and PNG paths that use it.
"""

import re
import struct
import time
from pathlib import Path

import pytest

from fastfoto_linux.library import jpeg_exif
from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.exif_errors import JpegExifError, XmpOrientationError
from fastfoto_linux.library.jpeg_exif import set_orientation as set_jpeg_orientation
from fastfoto_linux.library.plan import Action
from fastfoto_linux.library.png_exif import set_orientation as set_png_orientation
from fastfoto_linux.library.xmp_scan import MAX_XMP_BYTES, names_any_orientation
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import APP1, exif_bytes, segment, write_file
from tests.library.png_helpers import make_png, with_before_idat, xmp_packet
from tests.library.untrusted_helpers import insert_after_jfif, sideways, with_xmp

PNG = make_png(load_astronaut(), exif=exif_bytes(1))
EXTENSION_HEADER = b"http://ns.adobe.com/xmp/extension/\x00"
GUID = b"0123456789ABCDEF0123456789ABCDEF"
NAMESPACES = (
    b'xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    b'xmlns:tiff="http://ns.adobe.com/tiff/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"'
)


def doc(body: bytes, attributes: bytes = b"", *, head: bytes = b"") -> bytes:
    """A packet: ``head`` (declaration, DTD), then one description with ``body`` inside."""
    return (
        head + b"<x:xmpmeta " + NAMESPACES + b"><rdf:RDF><rdf:Description " + attributes + b">"
        b"" + body + b"</rdf:Description></rdf:RDF></x:xmpmeta>"
    )


# -- (1) a DTD can build or supply an Orientation -----------------------------------------------
ENTITY_BUILT = doc(
    b"&e;",
    head=b'<!DOCTYPE x [<!ENTITY e "<tiff:&#79;rientation>6</tiff:&#79;rientation>">]>',
)
ATTLIST_SUPPLIED = doc(
    b"", head=b'<!DOCTYPE x:xmpmeta [<!ATTLIST rdf:Description tiff:Orientation CDATA "1">]>'
)
DTD = {
    "entity builds an element (reported)": ENTITY_BUILT,
    "attlist supplies an attribute (reported)": ATTLIST_SUPPLIED,
    "lower case doctype": doc(b"", head=b"<!doctype x>"),
    "entity declaration alone": doc(b"", head=b'<!DOCTYPE x [<!ENTITY e "a">]>'),
    "attlist declaration alone": doc(b"", head=b'<!DOCTYPE x [<!attlist a b CDATA "1">]>'),
    "element declaration": doc(b"", head=b"<!DOCTYPE x [<!ELEMENT a ANY>]>"),
    "declaration after the root": doc(b"") + b"<!ENTITY e 'a'>",
}

# -- (2) an encoding the byte scan cannot read --------------------------------------------------
ENCODINGS = {
    "utf-7 declaration": b'<?xml version="1.0" encoding="UTF-7"?>' + doc(b"", b'dc:title="+AE8-"'),
    "cp037 declaration": b'<?xml version="1.0" encoding="cp037"?>' + doc(b""),
    "iso-8859-1 declaration": b'<?xml version="1.0" encoding="iso-8859-1"?>' + doc(b""),
    "single-quoted declaration": b"<?xml version='1.0' encoding='UTF-7'?>" + doc(b""),
    "upper case declaration": b'<?XML VERSION="1.0" ENCODING="UTF-7"?>' + doc(b""),
    "declaration after a byte order mark": b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-7"?>'
    + doc(b""),
    "declaration not at the start": b'<!-- -->\n<?xml version="1.0" encoding="UTF-7"?>' + doc(b""),
    "declaration with a malformed encoding": b'<?xml version="1.0" encoding=UTF-7?>' + doc(b""),
    "unterminated declaration": b'<?xml version="1.0" encoding="UTF-8"' + doc(b""),
    "ebcdic": doc(b"", b'tiff:Orientation="1"').decode().encode("cp037"),
    "ebcdic without any orientation": doc(b"").decode().encode("cp037"),
}
UTF8_PACKETS = {
    "no declaration": doc(b""),
    "utf-8 declaration": b'<?xml version="1.0" encoding="UTF-8"?>' + doc(b""),
    "lower case utf-8": b"<?xml version='1.0' encoding='utf-8'?>" + doc(b""),
    "no encoding in the declaration": b'<?xml version="1.0"?>' + doc(b""),
    "byte order mark and declaration": b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>'
    + doc(b""),
    "xpacket wrapper": b"<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>\n"
    + doc(b"")
    + b'\n<?xpacket end="w"?>',
}

# -- (3) markup is read, values and text are not ------------------------------------------------
NOT_ORIENTATION = {
    "caption value, equals sign": doc(b"", b'dc:description="Camera Orientation=portrait"'),
    "caption value, spaced": doc(b"", b'dc:title="Orientation = 3" dc:rights="x"'),
    "caption value, single quotes": doc(b"", b"dc:description='Orientation=1'"),
    "caption value, other quote inside": doc(b"", b"dc:description='say \"Orientation=1\" now'"),
    "caption value with an angle bracket": doc(b"", b'dc:description="a > b Orientation=1 <"'),
    "caption value with a tag-like word": doc(b"", b'dc:description="x <tiff:Make> y"'),
    "caption text": doc(b"<dc:description>Camera Orientation=portrait</dc:description>"),
    "keyword text": doc(
        b"<dc:subject><rdf:Bag><rdf:li>Orientation</rdf:li></rdf:Bag></dc:subject>"
    ),
    "keyword text with equals": doc(b"<rdf:li>Orientation=portrait</rdf:li>"),
    "escaped markup in text": doc(
        b"<dc:title>&lt;tiff:Orientation&gt;6&lt;/tiff:Orientation&gt;</dc:title>"
    ),
    "escaped markup in a value": doc(b"", b'dc:title="&lt;tiff:Orientation&gt;"'),
    "plain words in CDATA": doc(b"<dc:title><![CDATA[Camera Orientation=portrait]]></dc:title>"),
    "plain words in a comment": doc(b"<!-- Orientation=1, sensor Orientation -->"),
    "plain words in a processing instruction": doc(b"<?note Orientation=1?>"),
    "names that start with the word": doc(b"<x:Orientations/>", b'x:OrientationNote="a"'),
    "names that end with the word": doc(b"<x:PageOrientation/>", b'x:PageOrientation="a"'),
    "dashed prefix before the word": doc(b"", b'x-orientation="a"'),
}
ORIENTATION = {
    "attribute": doc(b"", b'tiff:Orientation="6"'),
    "attribute, no whitespace after the previous one": doc(
        b"", b'dc:title="1"tiff:Orientation="6"'
    ),
    "attribute, newline and tab": doc(b"", b'dc:title="1"\n\ttiff:Orientation\n=\t"6"'),
    "attribute, single quotes": doc(b"", b"tiff:Orientation='6'"),
    "attribute, after a value with an angle bracket": doc(
        b"", b'dc:title="x>y" tiff:Orientation="6"'
    ),
    "attribute, after a value with the other quote": doc(
        b"", b"""dc:title='"' tiff:Orientation="6\""""
    ),
    "attribute, any prefix": doc(b"", b'zz:Orientation="6"'),
    "attribute, no prefix": doc(b"", b'Orientation="6"'),
    "attribute, upper case": doc(b"", b'tiff:ORIENTATION="6"'),
    "attribute, lower case": doc(b"", b'tiff:orientation="6"'),
    "attribute, two prefixes": doc(b"", b'a:b:Orientation="6"'),
    "attribute, on a child": doc(b'<rdf:li tiff:Orientation="6"/>'),
    "element": doc(b"<tiff:Orientation>6</tiff:Orientation>"),
    "element, self-closing": doc(b"<tiff:Orientation/>"),
    "element, no prefix": doc(b"<Orientation>6</Orientation>"),
    "element, any case": doc(b"<tiff:oRiEnTaTiOn>6</tiff:oRiEnTaTiOn>"),
    "element, newline before the end of the tag": doc(b"<tiff:Orientation\n>6</tiff:Orientation>"),
    "element in a comment": doc(b"<!-- <tiff:Orientation>6</tiff:Orientation> -->"),
    "attribute in a comment": doc(b'<!-- <rdf:li tiff:Orientation="6"/> -->'),
    "element in CDATA": doc(b"<![CDATA[<tiff:Orientation>6</tiff:Orientation>]]>"),
    "element in a processing instruction": doc(b"<?x <tiff:Orientation>6?>"),
    "end tag only": doc(b"</tiff:Orientation>"),
}
MALFORMED = {
    "unterminated quote": doc(b"", b'dc:title="1 tiff:Make="x"'),
    "unterminated tag": b'<x:xmpmeta dc:title="1"',
    "unterminated tag name": b"<x:xmpmeta",
    "unterminated comment": doc(b"<!-- never closed"),
    "unterminated CDATA": doc(b"<![CDATA[ never closed"),
    "unterminated processing instruction": doc(b"<?pi never closed"),
    "unquoted value": doc(b"", b"tiff:Make=1"),
    "attribute without a value": doc(b"", b"tiff:Make"),
    "equals sign without a name": doc(b"", b'="1"'),
    "angle bracket in the text": b"<a> x < y </a>",
    "angle bracket at the end": doc(b"") + b"<",
    "character reference in a name": doc(b"<tiff:&#79;rientation>6</tiff:&#79;rientation>"),
    "character reference in an attribute name": doc(b"", b'tiff:&#79;rientation="6"'),
    "utf-7 plus sign in a name": doc(b"", b'tiff:+AE8-rientation="1"'),
    "end tag with an attribute": doc(b"</a b='1'>"),
    "end tag unterminated": doc(b"</a"),
    "empty tag name": doc(b"<>"),
    "bang that is neither a comment nor CDATA": doc(b"<!x>"),
}

SAME_ORIENTATION = {**ORIENTATION, **DTD, **MALFORMED}


def jpeg_skipped(tmp_path: Path, data: bytes) -> bool:
    write_file(tmp_path, "a.jpg", data)
    row = decide_file(tmp_path, "a.jpg")
    return (row.action, row.reason) == (Action.SKIP, "xmp-orientation")


def png_refused(packet: bytes) -> bool:
    png = with_before_idat(PNG, xmp_packet(packet, "itxt"))
    try:
        set_png_orientation(png, 6)
    except XmpOrientationError:
        return True
    return False


def extended(chunk: bytes, offset: int, total: int) -> bytes:
    return segment(APP1, EXTENSION_HEADER + GUID + struct.pack(">II", total, offset) + chunk)


@pytest.mark.parametrize("packet", SAME_ORIENTATION.values(), ids=SAME_ORIENTATION.keys())
def test_these_count_as_an_orientation_everywhere(tmp_path: Path, packet: bytes) -> None:
    assert names_any_orientation(packet)
    assert jpeg_skipped(tmp_path, with_xmp(sideways(90), packet))
    assert png_refused(packet)
    with pytest.raises(JpegExifError):
        set_jpeg_orientation(with_xmp(sideways(90), packet), 6)


@pytest.mark.parametrize("packet", ENCODINGS.values(), ids=ENCODINGS.keys())
def test_an_encoding_other_than_utf8_counts_as_an_orientation(
    tmp_path: Path, packet: bytes
) -> None:
    assert names_any_orientation(packet)
    assert jpeg_skipped(tmp_path, with_xmp(sideways(90), packet))
    assert png_refused(packet)


@pytest.mark.parametrize("packet", DTD.values(), ids=DTD.keys())
def test_a_dtd_counts_as_an_orientation_in_extended_xmp_too(tmp_path: Path, packet: bytes) -> None:
    data = insert_after_jfif(sideways(90), extended(packet, 0, len(packet)))
    assert jpeg_skipped(tmp_path, data)


@pytest.mark.parametrize(
    "packet",
    [*UTF8_PACKETS.values(), *NOT_ORIENTATION.values()],
    ids=[*UTF8_PACKETS, *NOT_ORIENTATION],
)
def test_ordinary_packets_are_not_refused(tmp_path: Path, packet: bytes) -> None:
    assert not names_any_orientation(packet)
    write_file(tmp_path, "a.jpg", with_xmp(sideways(90), packet))
    assert decide_file(tmp_path, "a.jpg").action is Action.ROTATE
    write_file(tmp_path, "b.jpg", insert_after_jfif(sideways(90), extended(packet, 0, len(packet))))
    assert decide_file(tmp_path, "b.jpg").action is Action.ROTATE
    assert not png_refused(packet)


# The scan before the tokenizer, to show it refuses nothing the new one lets through.
_OLD = re.compile(
    rb"<(?:[\w.\x80-\xff-]+:)?Orientation(?=[\s/>])|\s(?:[\w.\x80-\xff-]+:)?Orientation\s*="
)
CORPUS = {
    "lightroom": (
        b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 79.dabacbb">\n'
        b' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        b'  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        b'    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"\n'
        b'    xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        b'   xmp:CreatorTool="Adobe Photoshop Lightroom Classic 12.0 (Macintosh)"\n'
        b'   xmp:Rating="3" crs:Version="15.0" crs:Exposure2012="+0.35" crs:Sharpness="40">\n'
        b'   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Camera Orientation=portrait '
        b"shoot</rdf:li></rdf:Alt></dc:title>\n"
        b"   <dc:subject><rdf:Bag><rdf:li>Orientation</rdf:li><rdf:li>Tom &amp; Jerry's "
        b"&quot;best&quot;</rdf:li></rdf:Bag></dc:subject>\n"
        b"  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n"
        + b" " * 2000
        + b'\n<?xpacket end="w"?>'
    ),
    "exiftool": (
        b"<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>\n"
        b"<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='Image::ExifTool 12.50'>\n"
        b"<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>\n"
        b" <rdf:Description rdf:about='' xmlns:exif='http://ns.adobe.com/exif/1.0/'\n"
        b"  xmlns:photoshop='http://ns.adobe.com/photoshop/1.0/'>\n"
        b"  <exif:ExifVersion>0232</exif:ExifVersion>\n"
        b"  <photoshop:Instructions>Rotate: Orientation=6 was wrong</photoshop:Instructions>\n"
        b" </rdf:Description>\n</rdf:RDF>\n</x:xmpmeta>\n<?xpacket end='w'?>"
    ),
    "phone": (
        b'<?xml version="1.0" encoding="UTF-8"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description rdf:about="" xmlns:GCamera="http://ns.google.com/photos/1.0/camera/" '
        b'GCamera:SpecialTypeID="HDRP" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
        b'xmp:CreatorTool="Pixel" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        b'dc:description="Landscape Orientation > portrait Orientation = 1"/>'
        b"</rdf:RDF></x:xmpmeta>"
    ),
    "scanner": doc(b"<dc:title>Holiday</dc:title>", b'tiff:Make="Epson" tiff:Model="FF-680W"'),
    "with a comment and CDATA": doc(b"<!-- made by a tool --><dc:title><![CDATA[a<b]]></dc:title>"),
}


@pytest.mark.parametrize("packet", CORPUS.values(), ids=CORPUS.keys())
def test_ordinary_corpus_is_accepted(
    packet: bytes,
) -> None:
    assert not names_any_orientation(packet)


def test_nothing_is_refused_that_the_old_scan_let_through_and_captions_no_longer_are() -> None:
    refused_before_only = [
        name
        for name, packet in CORPUS.items()
        if _OLD.search(packet) and not names_any_orientation(packet)
    ]
    # Packets with a caption that the old scan took for an attribute are accepted now.
    assert set(refused_before_only) == {"lightroom", "exiftool", "phone"}
    for name, packet in ORIENTATION.items():
        assert names_any_orientation(packet), name


# -- performance: nothing the size cap lets through may take long to scan -----------------------
def hostile() -> dict[str, bytes]:
    word = b" orientation "
    shapes = {
        "empty elements": b"<a/>" * (MAX_XMP_BYTES // 4),
        "many attributes": b"<a " + b'b="1" ' * (MAX_XMP_BYTES // 6),
        "unterminated comments": b"<!--" * (MAX_XMP_BYTES // 4),
        "unterminated tags": b"<a " * (MAX_XMP_BYTES // 3),
        "quotes": b'"' * MAX_XMP_BYTES,
        "angle brackets": b"<" * MAX_XMP_BYTES,
        "xml declarations": b"<?xml ?>" * (MAX_XMP_BYTES // 8),
        "long name": b"<" + b"a" * (MAX_XMP_BYTES - 2) + b">",
        "long prefix chain": b"<" + b"a:" * (MAX_XMP_BYTES // 2 - 2) + b"b>",
        "values with angle brackets": b'<a b="' + b"<a b='1' " * (MAX_XMP_BYTES // 10),
        "attributes with colons": b"<a " + b"x:y:z=''" * (MAX_XMP_BYTES // 9),
    }
    return {
        **{name: data[:MAX_XMP_BYTES] for name, data in shapes.items()},
        **{
            f"{name} and the word": (data[: MAX_XMP_BYTES - len(word)] + word)
            for name, data in shapes.items()
        },
    }


@pytest.mark.parametrize("name", list(hostile()))
def test_a_packet_at_the_size_cap_is_scanned_in_under_a_second(name: str) -> None:
    data = hostile()[name]
    assert len(data) <= MAX_XMP_BYTES
    started = time.perf_counter()
    names_any_orientation(data)
    assert time.perf_counter() - started < 1.0


# -- (4) Extended XMP is not joined before its size is checked ----------------------------------
def test_extended_xmp_over_the_cap_is_never_joined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def joined(parts):
        raise AssertionError("an oversized packet was joined")

    monkeypatch.setattr(jpeg_exif, "_tiled", joined)
    chunk = b" " * 60_000
    count = MAX_XMP_BYTES // len(chunk) + 2
    total = len(chunk) * count
    chunks = b"".join(extended(chunk, i * len(chunk), total) for i in range(count))
    assert jpeg_skipped(tmp_path, insert_after_jfif(sideways(90), chunks))


def test_extended_xmp_that_declares_more_than_the_cap_is_never_joined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def joined(parts):
        raise AssertionError("an oversized packet was joined")

    monkeypatch.setattr(jpeg_exif, "_tiled", joined)
    data = insert_after_jfif(sideways(90), extended(b"<a/>", 0, MAX_XMP_BYTES + 1))
    assert jpeg_skipped(tmp_path, data)
