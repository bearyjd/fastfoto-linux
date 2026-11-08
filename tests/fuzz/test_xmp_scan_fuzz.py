"""Fuzz the shared XMP orientation scan (``library/xmp_scan``).

Property: ``names_any_orientation`` returns a ``bool`` for any bytes, never raises and is never
slow (the Hypothesis deadline). It fails closed: a DOCTYPE, an entity, a NUL byte, a declaration
that is misplaced or not UTF-8, malformed markup, an oversized packet and any Orientation tag or
attribute all give ``True``, and junk around such a packet cannot turn that into ``False``. A
clean well-formed packet gives ``False``, with or without an Orientation in its text.
"""

import time

from hypothesis import given
from hypothesis import strategies as st

from fastfoto_linux.library.xmp_scan import MAX_XMP_BYTES, names_any_orientation
from tests.library.xmp_helpers import doc

CLEAN = doc(b"<dc:title>holiday</dc:title>", b'dc:format="image/jpeg"')
ORIENTED = doc(b"<tiff:Orientation>6</tiff:Orientation>")
ORIENTED_ATTRIBUTE = doc(b"", b'tiff:Orientation="6"')
DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>'
SEEDS = [CLEAN, ORIENTED, ORIENTED_ATTRIBUTE, DECLARATION + CLEAN, b"\xef\xbb\xbf" + CLEAN]
TIME_BUDGET = 2.0  # seconds: a linear scan of a small packet is far below this

# Text that is plain character data: no markup, no NUL, no ampersand, no declaration.
SAFE_TEXT = st.text(
    alphabet=st.characters(
        blacklist_characters="<>&\x00\r", blacklist_categories=("Cs", "Cc"), max_codepoint=0x2FFF
    ),
    max_size=40,
).map(lambda s: s.encode("utf-8"))
ORIENTATION_NAME = st.sampled_from(
    [
        b"tiff:Orientation",
        b"Orientation",
        b"x:ORIENTATION",
        b"a.b:orientation",
        b"\xc3\xa9:Orientation",
    ]
)
FOREIGN_ENCODINGS = [b"UTF-16", b"utf-7", b"cp037", b"ISO-8859-1", b"UTF-32", b"US-ASCII", b""]


def _scan(packet: bytes) -> bool:
    started = time.perf_counter()
    result = names_any_orientation(packet)
    assert isinstance(result, bool)
    assert time.perf_counter() - started < TIME_BUDGET
    return result


def _mutated(data: st.DataObject, seed: bytes) -> bytes:
    raw = bytearray(seed)
    for _ in range(data.draw(st.integers(1, 5))):
        action = data.draw(st.sampled_from(["flip", "insert", "delete", "cut"]))
        at = data.draw(st.integers(0, max(len(raw) - 1, 0)))
        if action == "flip" and raw:
            raw[at] = data.draw(st.integers(0, 255))
        elif action == "insert":
            raw[at:at] = data.draw(st.binary(max_size=12))
        elif action == "delete":
            del raw[at : at + data.draw(st.integers(1, 8))]
        else:
            del raw[at:]
    return bytes(raw)


def test_the_seed_packets_behave_as_documented() -> None:
    assert not names_any_orientation(CLEAN)
    assert not names_any_orientation(DECLARATION + CLEAN)
    assert names_any_orientation(ORIENTED)
    assert names_any_orientation(ORIENTED_ATTRIBUTE)


@given(data=st.binary(max_size=400))
def test_arbitrary_bytes_never_crash(data: bytes) -> None:
    _scan(data)
    _scan(CLEAN + data)
    _scan(data + CLEAN)


@given(
    text=st.text(max_size=200), encoding=st.sampled_from(["utf-8", "utf-16", "utf-32", "latin-1"])
)
def test_arbitrary_text_in_any_encoding_never_crashes(text: str, encoding: str) -> None:
    _scan(text.encode(encoding, errors="replace"))
    _scan(("\ufeff" + text).encode(encoding, errors="replace"))


@given(data=st.data(), seed=st.sampled_from(SEEDS))
def test_mutated_packets_never_crash(data: st.DataObject, seed: bytes) -> None:
    _scan(_mutated(data, seed))


@given(seed=st.sampled_from(SEEDS), cut=st.integers(0, 400))
def test_every_prefix_of_a_packet_never_crashes(seed: bytes, cut: int) -> None:
    _scan(seed[:cut])


@given(depth=st.integers(1, 5000), name=st.sampled_from([b"a", b"x:very-long-name" * 8]))
def test_deeply_nested_elements_are_scanned_quickly(depth: int, name: bytes) -> None:
    nested = b"<" + name + b">"
    packet = nested * depth + (b"</" + name + b">") * depth
    _scan(packet)
    _scan(packet[: len(packet) // 2])


@given(
    count=st.integers(1, 800),
    piece=st.sampled_from(
        [
            b"<a ",
            b'<a b="',
            b"<!--",
            b"<![CDATA[",
            b"<?",
            b'<a b="1" ',
            b"</",
            b"<a/><",
            b"<a b='",
        ]
    ),
)
def test_repeated_unterminated_constructs_are_refused_quickly(count: int, piece: bytes) -> None:
    assert _scan(piece * count)
    assert _scan(CLEAN + piece * count)


@given(count=st.integers(1, 300), whitespace=st.sampled_from([b" ", b"\t\n", b"  = "]))
def test_long_attribute_runs_are_scanned_quickly(count: int, whitespace: bytes) -> None:
    attributes = b"".join(b"k%d" % i + b"=" + b'"v"' + whitespace for i in range(count))
    _scan(doc(b"", attributes))
    _scan(doc(b"", attributes + b"tiff:Orientation"))


@given(size=st.sampled_from([MAX_XMP_BYTES + 1, MAX_XMP_BYTES + 4096, MAX_XMP_BYTES * 2]))
def test_an_oversized_packet_counts_without_being_scanned(size: int) -> None:
    assert _scan(b" " * size)
    assert _scan(CLEAN + b" " * size)


@given(
    size=st.sampled_from([MAX_XMP_BYTES - 1, MAX_XMP_BYTES]),
    filler=st.sampled_from([b" ", b"a", b"<a>"]),
)
def test_a_packet_at_the_cap_is_scanned_in_time(size: int, filler: bytes) -> None:
    body = (filler * (size // len(filler) + 1))[: size - len(CLEAN)]
    _scan(CLEAN + body)


@given(data=st.binary(max_size=200), position=st.integers(0, 3))
def test_a_nul_byte_always_counts(data: bytes, position: int) -> None:
    cut = min(position * 50, len(data))
    assert _scan(data[:cut] + b"\x00" + data[cut:])


@given(
    text=st.text(alphabet='<?xml version="1.0"> ', max_size=30),
    encoding=st.sampled_from(["utf-16", "utf-16-le", "utf-16-be", "utf-32", "cp037"]),
)
def test_encoded_wide_or_ebcdic_packets_count(text: str, encoding: str) -> None:
    assert _scan((DECLARATION.decode() + CLEAN.decode() + text).encode(encoding))
    if encoding != "cp037":  # without a declaration EBCDIC is just text with no markup in it
        assert _scan(CLEAN.decode().encode(encoding))


@given(
    head=st.sampled_from(
        [
            b"<!DOCTYPE x>",
            b"<!doctype x [<!ENTITY e 'a'>]>",
            b"<!ENTITY e 'a'>",
            b"<!ATTLIST a b CDATA '1'>",
            b"<!ELEMENT a ANY>",
        ]
    ),
    junk=SAFE_TEXT,
)
def test_a_dtd_always_counts(head: bytes, junk: bytes) -> None:
    assert _scan(head + CLEAN)
    assert _scan(DECLARATION + head + CLEAN)
    assert _scan(CLEAN + head + junk)


@given(
    encoding=st.sampled_from(FOREIGN_ENCODINGS),
    quote=st.sampled_from([b'"', b"'"]),
    spaces=st.sampled_from([b"", b" "]),
)
def test_a_declaration_naming_a_foreign_encoding_counts(
    encoding: bytes, quote: bytes, spaces: bytes
) -> None:
    declaration = (
        b"<?xml version="
        + quote
        + b"1.0"
        + quote
        + b" encoding"
        + spaces
        + b"="
        + spaces
        + quote
        + encoding
        + quote
        + b"?>"
    )
    assert _scan(declaration + CLEAN)


@given(spelling=st.sampled_from([b"utf-8", b"UTF-8", b"Utf-8"]), junk=SAFE_TEXT)
def test_a_utf8_declaration_at_the_start_is_accepted(spelling: bytes, junk: bytes) -> None:
    declaration = b'<?xml version="1.0" encoding="' + spelling + b'"?>'
    assert not _scan(declaration + doc(b"<dc:title>" + junk + b"</dc:title>"))
    assert not _scan(b"\xef\xbb\xbf" + declaration + CLEAN)


@given(junk=SAFE_TEXT)
def test_a_misplaced_or_repeated_declaration_counts(junk: bytes) -> None:
    assert _scan(junk + b" " + DECLARATION + CLEAN)
    assert _scan(CLEAN + DECLARATION)
    assert _scan(DECLARATION + DECLARATION + CLEAN)
    assert _scan(b" " + DECLARATION + CLEAN)


@given(name=ORIENTATION_NAME, value=st.integers(1, 8), junk=SAFE_TEXT)
def test_an_orientation_element_or_attribute_counts(name: bytes, value: int, junk: bytes) -> None:
    number = str(value).encode()
    assert _scan(doc(b"<" + name + b">" + number + b"</" + name + b">"))
    assert _scan(doc(b"", name + b'="' + number + b'"'))
    assert _scan(doc(b"", b"dc:format='x' " + name + b"='" + number + b"'"))
    assert _scan(doc(b"<" + name + b" " + junk.replace(b'"', b"") + b"/>"))


@given(value=st.integers(1, 8), orientations=st.integers(2, 4), same=st.booleans())
def test_ambiguous_or_duplicate_orientations_count(
    value: int, orientations: int, same: bool
) -> None:
    body = b"".join(
        b"<tiff:Orientation>%d</tiff:Orientation>" % (value if same else (value + i) % 8 + 1)
        for i in range(orientations)
    )
    assert _scan(doc(body))
    assert _scan(doc(body, b'tiff:Orientation="%d"' % value))


@given(junk=SAFE_TEXT, value=st.integers(1, 8))
def test_text_and_values_that_merely_mention_orientation_are_not_one(
    junk: bytes, value: int
) -> None:
    caption = b"Orientation=portrait " + junk + b" tiff:Orientation %d" % value
    assert not _scan(doc(b"<dc:description>" + caption + b"</dc:description>"))
    assert not _scan(doc(b"", b'dc:description="' + caption.replace(b'"', b"") + b'"'))
    assert not _scan(
        doc(b"<dc:title>" + junk + b"</dc:title><!-- " + junk.replace(b"-", b"") + b" -->")
    )


@given(
    prefix=st.binary(max_size=60),
    suffix=st.binary(max_size=60),
    seed=st.sampled_from([ORIENTED, ORIENTED_ATTRIBUTE, DECLARATION + ORIENTED]),
)
def test_junk_around_an_oriented_packet_never_clears_it(
    prefix: bytes, suffix: bytes, seed: bytes
) -> None:
    assert _scan(prefix + seed + suffix)


@given(prefix=SAFE_TEXT, suffix=SAFE_TEXT)
def test_plain_text_around_a_clean_packet_does_not_add_an_orientation(
    prefix: bytes, suffix: bytes
) -> None:
    assert not _scan(prefix + CLEAN + suffix)
