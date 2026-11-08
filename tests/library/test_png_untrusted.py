"""A hostile PNG is refused with a reason code, before Pillow or the writer trusts any of it."""

import io
import struct
import zlib

import pytest
from PIL import Image

from fastfoto_linux.library import png_exif
from fastfoto_linux.library.exif_errors import (
    ExifMalformedError,
    ExifTooLargeError,
    ImageTooLargeError,
    JpegExifError,
    NotAPngError,
    TooManySegmentsError,
    UnsupportedPngError,
    XmpOrientationError,
)
from fastfoto_linux.library.png_exif import Layout, decoder_copy, read_orientation, set_orientation
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import exif_bytes
from tests.library.png_helpers import (
    COMPETING_XMP,
    ORIENTATION_XMP,
    PLAIN_XMP,
    SIGNATURE,
    assemble,
    corrupt_crc,
    ihdr,
    kinds,
    make_png,
    split,
    text_chunk,
    with_after_idat,
    with_before_idat,
    xmp_packet,
)
from tests.photo_edits.png_helpers import pixels

BASE = make_png(load_astronaut(), exif=exif_bytes(1))
PALETTE = make_png(pixels(), mode="P")
CARRIERS = ("itxt", "itxt-compressed", "ztxt", "tEXt")


def rebuilt(png: bytes, header: bytes) -> bytes:
    return assemble([(b"IHDR", header), *split(png)[1:]])


def two_idats(png: bytes) -> list[tuple[bytes, bytes]]:
    chunks = split(png)
    at = kinds(png).index(b"IDAT")
    data = chunks[at][1]
    half = len(data) // 2
    return [*chunks[:at], (b"IDAT", data[:half]), (b"IDAT", data[half:]), *chunks[at + 1 :]]


def interrupted_idats(png: bytes) -> list[tuple[bytes, bytes]]:
    chunks = two_idats(png)
    at = kinds(png).index(b"IDAT")
    return [*chunks[: at + 1], (b"tEXt", b"a\x00b"), *chunks[at + 1 :]]


def image_data_first(png: bytes) -> list[tuple[bytes, bytes]]:
    chunks = split(png)
    at = kinds(png).index(b"IDAT")
    return [chunks[at], *chunks[:at], *chunks[at + 1 :]]


def without(png: bytes, kind: bytes) -> bytes:
    return assemble([c for c in split(png) if c[0] != kind])


def palette_chunk(png: bytes) -> tuple[bytes, bytes]:
    return next(c for c in split(png) if c[0] == b"PLTE")


# --- structure ------------------------------------------------------------------------------

MALFORMED = {
    "no-signature": b"\x89PNX" + BASE[4:],
    "truncated-in-a-chunk": BASE[:-20],
    "truncated-after-signature": SIGNATURE,
    "bad-crc-on-ancillary-chunk": corrupt_crc(
        with_before_idat(BASE, text_chunk(b"k", b"v")), b"tEXt"
    ),
    "bad-crc-on-ihdr": corrupt_crc(BASE, b"IHDR"),
    "bad-crc-on-idat": corrupt_crc(BASE, b"IDAT"),
    "ihdr-wrong-length": assemble([(b"IHDR", ihdr(8, 6) + b"\x00"), *split(BASE)[1:]]),
    "second-ihdr": with_before_idat(BASE, (b"IHDR", ihdr(8, 6))),
    "ihdr-not-first": assemble([split(BASE)[1], split(BASE)[0], *split(BASE)[2:]]),
    "no-iend": assemble(split(BASE)[:-1]),
    "no-idat": assemble([c for c in split(BASE) if c[0] != b"IDAT"]),
    "bytes-after-iend": BASE + b"trailing",
    "idat-not-consecutive": assemble(interrupted_idats(BASE)),
    "plte-after-idat": with_after_idat(without(PALETTE, b"PLTE"), palette_chunk(PALETTE)),
    "zero-width": rebuilt(BASE, ihdr(0, 6)),
    "zero-height": rebuilt(BASE, ihdr(8, 0)),
    "width-over-31-bits": rebuilt(BASE, ihdr(2**31, 6)),
    "depth-colour-mismatch": rebuilt(BASE, ihdr(8, 6, depth=8, colour=1)),
    "depth-16-palette": rebuilt(BASE, ihdr(8, 6, depth=16, colour=3)),
    "bad-interlace": rebuilt(BASE, ihdr(8, 6, interlace=2)),
    "bad-compression-method": rebuilt(BASE, ihdr(8, 6)[:10] + b"\x01\x00\x00"),
    "palette-not-a-multiple-of-three": with_before_idat(
        without(PALETTE, b"PLTE"), (b"PLTE", palette_chunk(PALETTE)[1] + b"\x00")
    ),
    "palette-empty": with_before_idat(without(PALETTE, b"PLTE"), (b"PLTE", b"")),
    "palette-over-256-entries": with_before_idat(without(PALETTE, b"PLTE"), (b"PLTE", bytes(771))),
    "second-palette": with_before_idat(PALETTE, palette_chunk(PALETTE)),
    "idat-before-ihdr": assemble(image_data_first(BASE)),
    "chunk-type-not-letters": with_before_idat(BASE, (b"a1cd", b"")),
    "chunk-length-past-the-end": BASE[:8] + struct.pack(">I", 2**31 - 1) + BASE[12:],
    "iend-with-data": assemble([*split(BASE)[:-1], (b"IEND", b"x")]),
}


@pytest.mark.parametrize("name", MALFORMED)
def test_a_malformed_stream_is_refused_as_not_a_png(name: str) -> None:
    with pytest.raises(NotAPngError):
        Layout.of(MALFORMED[name])


UNSUPPORTED = {
    "animated": with_before_idat(BASE, (b"acTL", struct.pack(">II", 1, 0))),
    "unknown-critical-chunk": with_before_idat(BASE, (b"ABCD", b"x")),
}


@pytest.mark.parametrize("name", UNSUPPORTED)
def test_what_the_tool_cannot_keep_intact_is_refused(name: str) -> None:
    with pytest.raises(UnsupportedPngError) as caught:
        Layout.of(UNSUPPORTED[name])
    assert caught.value.reason == "unsupported-png"


def test_a_unknown_ancillary_chunk_is_tolerated_and_kept() -> None:
    png = with_before_idat(BASE, (b"zzZz", b"private"))
    edited = set_orientation(png, 6)
    assert (b"zzZz", b"private") in split(edited)


def ordered_palette_png(*, gamma_after_palette: bool) -> bytes:
    chunks = split(PALETTE)
    at = kinds(PALETTE).index(b"PLTE")
    gamma = (b"gAMA", b"\x00\x00\xb1\x8f")
    around = [chunks[at], gamma] if gamma_after_palette else [gamma, chunks[at]]
    return assemble(
        [*chunks[:at], *around, (b"tRNS", b"\x00"), (b"pHYs", bytes(9)), *chunks[at + 1 :]]
    )


def test_a_png_with_the_usual_ancillary_chunks_in_spec_order_passes() -> None:
    png = ordered_palette_png(gamma_after_palette=False)
    assert read_orientation(set_orientation(png, 6)) == 6


def test_ancillary_chunk_order_is_not_policed_and_the_chunks_stay_where_they_were() -> None:
    # gAMA must precede PLTE in the spec; this tool rewrites no colour chunk and Pillow reads such
    # files, so the order is accepted and left exactly as found.
    png = ordered_palette_png(gamma_after_palette=True)
    edited = set_orientation(png, 6)
    assert [k for k in kinds(edited) if k != b"eXIf"] == kinds(png)


def test_too_many_chunks_before_the_image_are_refused() -> None:
    many = [(b"tEXt", b"k\x00v")] * (png_exif.MAX_CHUNKS + 1)
    with pytest.raises(TooManySegmentsError):
        Layout.of(with_before_idat(BASE, *many))


def test_a_long_run_of_image_data_chunks_is_fine() -> None:
    chunks = split(BASE)
    at = kinds(BASE).index(b"IDAT")
    data = chunks[at][1]
    pieces = [(b"IDAT", data[i : i + 8]) for i in range(0, len(data), 8)]
    png = assemble([*chunks[:at], *pieces, *chunks[at + 1 :]])
    assert len(pieces) > png_exif.MAX_CHUNKS
    assert read_orientation(png) == 1


# --- eXIf placement and size ----------------------------------------------------------------


def test_two_exif_chunks_are_refused() -> None:
    (exif,) = (c for c in split(BASE) if c[0] == b"eXIf")
    with pytest.raises(ExifMalformedError):
        Layout.of(with_before_idat(BASE, exif))


def test_an_exif_chunk_after_the_image_data_is_refused() -> None:
    late = with_after_idat(without(BASE, b"eXIf"), (b"eXIf", exif_bytes(1)[6:]))
    with pytest.raises(ExifMalformedError):
        Layout.of(late)


def test_an_oversized_exif_chunk_is_refused() -> None:
    big = exif_bytes(1, ImageDescription="x" * 70_000)[6:]
    with pytest.raises(ExifTooLargeError):
        Layout.of(with_before_idat(make_png(pixels()), (b"eXIf", big)))


def test_an_edit_that_would_make_the_exif_chunk_too_large_is_refused() -> None:
    base = len(exif_bytes(None, ImageDescription=""))
    near = exif_bytes(None, ImageDescription="x" * (png_exif.MAX_EXIF_CHUNK - base))[6:]
    png = with_before_idat(make_png(pixels()), (b"eXIf", near))
    assert len(near) <= png_exif.MAX_EXIF_CHUNK
    with pytest.raises(ExifTooLargeError):
        set_orientation(png, 6)


# --- size claims ----------------------------------------------------------------------------


def test_the_header_size_is_reported_without_decoding_anything() -> None:
    huge = rebuilt(BASE, ihdr(60_000, 60_000))
    assert png_exif.pixel_count(huge) == 60_000 * 60_000


# --- XMP and legacy metadata ----------------------------------------------------------------


@pytest.mark.parametrize("carrier", CARRIERS)
def test_an_xmp_orientation_in_any_carrier_blocks_the_edit(carrier: str) -> None:
    png = with_before_idat(BASE, xmp_packet(ORIENTATION_XMP, carrier))
    with pytest.raises(XmpOrientationError):
        set_orientation(png, 6)


@pytest.mark.parametrize("name", COMPETING_XMP)
def test_any_xmp_orientation_under_any_spelling_blocks_the_edit(name: str) -> None:
    png = with_before_idat(BASE, xmp_packet(COMPETING_XMP[name], "itxt"))
    with pytest.raises(XmpOrientationError):
        set_orientation(png, 6)


def test_an_xmp_orientation_spelled_with_a_character_reference_is_blocked_when_compressed() -> None:
    packet = COMPETING_XMP["character-reference-in-namespace"]
    png = with_before_idat(BASE, xmp_packet(packet, "ztxt"))
    with pytest.raises(XmpOrientationError):
        set_orientation(png, 6)


def test_an_xmp_orientation_in_the_second_of_two_packets_blocks_the_edit() -> None:
    png = with_before_idat(
        BASE, xmp_packet(PLAIN_XMP, "itxt"), xmp_packet(ORIENTATION_XMP, "itxt-compressed")
    )
    with pytest.raises(XmpOrientationError):
        set_orientation(png, 6)


@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("packet", [PLAIN_XMP])
def test_xmp_without_a_tiff_orientation_does_not_block_the_edit(
    carrier: str, packet: bytes
) -> None:
    png = with_before_idat(BASE, xmp_packet(packet, carrier))
    assert read_orientation(set_orientation(png, 6)) == 6


def test_a_compressed_xmp_packet_that_unpacks_too_large_is_refused_not_expanded() -> None:
    bomb = zlib.compress(b" " * (png_exif.MAX_XMP_BYTES + 1) + ORIENTATION_XMP)
    png = with_before_idat(BASE, (b"iTXt", b"XML:com.adobe.xmp\x00\x01\x00\x00\x00" + bomb))
    with pytest.raises(XmpOrientationError):
        set_orientation(png, 6)


def test_a_compressed_xmp_packet_cut_short_is_refused() -> None:
    cut = zlib.compress(PLAIN_XMP)[:-6]  # what is left does not name an orientation
    png = with_before_idat(BASE, (b"iTXt", b"XML:com.adobe.xmp\x00\x01\x00\x00\x00" + cut))
    with pytest.raises(XmpOrientationError):
        set_orientation(png, 6)


def test_an_uncompressed_xmp_packet_over_the_limit_is_refused() -> None:
    big = PLAIN_XMP + b" " * png_exif.MAX_XMP_BYTES
    with pytest.raises(XmpOrientationError):
        set_orientation(with_before_idat(BASE, xmp_packet(big, "tEXt")), 6)


@pytest.mark.parametrize("head", [b"\x02\x00\x00\x00", b"\x01\x01\x00\x00", b"\x00\x01\x00\x00"])
def test_an_xmp_itxt_chunk_with_an_unknown_compression_is_refused(head: bytes) -> None:
    png = with_before_idat(
        BASE, (b"iTXt", b"XML:com.adobe.xmp\x00" + head + zlib.compress(PLAIN_XMP))
    )
    with pytest.raises(XmpOrientationError):
        set_orientation(png, 6)


def test_a_compressed_xmp_packet_that_is_not_zlib_is_refused() -> None:
    png = with_before_idat(BASE, (b"iTXt", b"XML:com.adobe.xmp\x00\x01\x00\x00\x00" + b"garbage"))
    with pytest.raises(XmpOrientationError):
        set_orientation(png, 6)


def test_an_xmp_itxt_chunk_that_is_cut_short_is_refused() -> None:
    for tail in (b"", b"\x00", b"\x00\x00", b"\x00\x00lang"):
        png = with_before_idat(BASE, (b"iTXt", b"XML:com.adobe.xmp\x00" + tail))
        with pytest.raises(XmpOrientationError):
            set_orientation(png, 6)


@pytest.mark.parametrize("keyword", [b"Raw profile type exif", b"raw profile type APP1"])
def test_a_legacy_exif_text_profile_blocks_the_edit(keyword: str) -> None:
    png = with_before_idat(BASE, text_chunk(keyword, b"\nexif\n 4\n00000000\n"))
    with pytest.raises(UnsupportedPngError):
        set_orientation(png, 6)


def test_ordinary_text_chunks_do_not_block_the_edit() -> None:
    png = with_before_idat(BASE, text_chunk(b"Comment", b"hello"), text_chunk(b"Software", b"x"))
    assert read_orientation(set_orientation(png, 6)) == 6


# --- what Pillow is given -------------------------------------------------------------------


def test_the_decoder_copy_has_only_the_chunks_decoding_needs() -> None:
    bomb = zlib.compress(b"0" * 20_000_000)
    png = with_before_idat(
        make_png(load_astronaut(), exif=exif_bytes(6)),
        (b"zTXt", b"k\x00\x00" + bomb),
        (b"iCCP", b"p\x00\x00" + bomb),
        (b"iTXt", b"k\x00\x00\x00\x00\x00" + b"t"),
        (b"pHYs", bytes(9)),
        xmp_packet(ORIENTATION_XMP, "itxt-compressed"),
        (b"tRNS", b""),
    )
    copy = decoder_copy(png)
    assert set(kinds(copy)) == {b"IHDR", b"eXIf", b"IDAT", b"IEND"}
    assert bomb not in copy
    with Image.open(io.BytesIO(copy)) as image:
        image.load()


def test_the_decoder_copy_of_a_palette_image_keeps_the_palette() -> None:
    assert b"PLTE" in kinds(decoder_copy(PALETTE))


def test_the_decoder_copy_checks_the_exif_block_first() -> None:
    bad = with_before_idat(make_png(pixels()), (b"eXIf", b"MM\x00*\xff\xff\xff\xff"))
    with pytest.raises(JpegExifError):
        decoder_copy(bad)


def test_the_edited_file_is_size_checked_before_pillow_opens_it(monkeypatch) -> None:
    monkeypatch.setattr(png_exif, "MAX_IMAGE_PIXELS", 10)
    monkeypatch.setattr(png_exif.Image, "open", lambda *a, **k: pytest.fail("opened"))
    with pytest.raises(ImageTooLargeError):
        set_orientation(BASE, 6)
