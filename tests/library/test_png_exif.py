"""Changing the Orientation of a PNG: one eXIf chunk is patched or inserted, nothing else moves."""

import io

import pytest
from PIL import Image

from fastfoto_linux.library import png_exif
from fastfoto_linux.library.exif_errors import (
    ExifMalformedError,
    JpegExifError,
    NotAPngError,
)
from fastfoto_linux.library.png_exif import Layout, pixel_count, read_orientation, set_orientation
from fastfoto_linux.photo_edits.png_guard import check_png
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import ORIENTATION, exif_bytes
from tests.library.png_helpers import (
    assemble,
    idat_bytes,
    kinds,
    make_png,
    split,
    with_before_idat,
)
from tests.photo_edits.png_helpers import master_png, one_tag_tiff, pixels

PORTRAIT = load_astronaut()


def pillow_tag(png: bytes) -> int | None:
    with Image.open(io.BytesIO(png)) as image:
        return image.getexif().get(ORIENTATION)


def others(png: bytes) -> list[tuple[bytes, bytes]]:
    return [c for c in split(png) if c[0] != b"eXIf"]


# --- reading --------------------------------------------------------------------------------


@pytest.mark.parametrize("tag", [1, 3, 6, 8])
def test_the_stored_tag_is_read(tag: int) -> None:
    assert read_orientation(make_png(PORTRAIT, exif=exif_bytes(tag))) == tag


def test_a_little_endian_block_is_read() -> None:
    assert read_orientation(make_png(PORTRAIT, exif=exif_bytes(6, little_endian=True))) == 6


def test_no_exif_chunk_and_no_tag_both_read_as_none() -> None:
    assert read_orientation(make_png(PORTRAIT)) is None
    assert read_orientation(make_png(PORTRAIT, exif=exif_bytes(None))) is None


def test_an_exif_block_with_the_jpeg_prefix_is_malformed() -> None:
    png = with_before_idat(make_png(PORTRAIT), (b"eXIf", exif_bytes(6)))  # "Exif\0\0" kept
    with pytest.raises(ExifMalformedError):
        read_orientation(png)


def test_pixel_count_is_the_header_size_in_rgb_equivalents() -> None:
    assert pixel_count(make_png(pixels())) == 8 * 6
    rgba = make_png(pixels(), mode="RGBA")
    assert pixel_count(rgba) == 64
    assert pixel_count(make_png(pixels(), mode="L")) == 48


# --- writing: an existing tag ---------------------------------------------------------------


@pytest.mark.parametrize("tag", [1, 3, 6, 8])
def test_an_existing_tag_is_patched_and_every_other_chunk_is_untouched(tag: int) -> None:
    png = make_png(PORTRAIT, exif=exif_bytes(6, date=True))
    edited = set_orientation(png, tag)
    assert read_orientation(edited) == tag
    assert pillow_tag(edited) == tag
    assert others(edited) == others(png)
    assert idat_bytes(edited) == idat_bytes(png)
    assert len(edited) == len(png)
    (before,) = (d for k, d in split(png) if k == b"eXIf")
    (after,) = (d for k, d in split(edited) if k == b"eXIf")
    assert len(after) == len(before)


def test_the_patched_chunk_has_a_fresh_crc_and_the_file_still_decodes() -> None:
    edited = set_orientation(make_png(PORTRAIT, exif=exif_bytes(6)), 3)
    Layout.of(edited)  # every CRC is checked here
    with Image.open(io.BytesIO(edited)) as image:
        assert image.size == (PORTRAIT.shape[1], PORTRAIT.shape[0])
        image.load()


# --- writing: no tag yet --------------------------------------------------------------------


def test_a_missing_exif_chunk_is_inserted_right_before_the_image_data() -> None:
    png = make_png(PORTRAIT)
    edited = set_orientation(png, 6)
    assert read_orientation(edited) == 6
    assert pillow_tag(edited) == 6
    assert kinds(edited).count(b"eXIf") == 1
    assert kinds(edited).index(b"eXIf") + 1 == kinds(edited).index(b"IDAT")
    assert others(edited) == split(png)
    assert idat_bytes(edited) == idat_bytes(png)


def test_a_block_without_a_tag_gets_one_and_keeps_its_other_entries() -> None:
    png = make_png(PORTRAIT, exif=exif_bytes(None, date=True))
    edited = set_orientation(png, 8)
    assert read_orientation(edited) == 8
    with Image.open(io.BytesIO(edited)) as image:
        exif = image.getexif()
        assert exif[0x010F] == "TestCam"
        assert exif.get_ifd(0x8769)[0x9003] == "1975:06:14 12:30:00"
    assert others(edited) == others(png)


def test_an_edited_master_still_passes_the_editors_png_guard() -> None:
    check_png(set_orientation(master_png(), 6))
    bare = assemble([c for c in split(master_png()) if c[0] != b"eXIf"])
    check_png(set_orientation(bare, 6))


def test_a_tag_outside_one_to_eight_is_refused() -> None:
    png = make_png(PORTRAIT)
    for bad in (0, 9, -1):
        with pytest.raises(ValueError):
            set_orientation(png, bad)


def test_the_layout_can_be_passed_in_and_gives_the_same_result() -> None:
    png = make_png(PORTRAIT, exif=exif_bytes(1))
    layout = Layout.of(png)
    assert read_orientation(png, layout) == 1
    assert set_orientation(png, 6, layout) == set_orientation(png, 6)


def test_an_exif_block_that_points_outside_itself_is_refused() -> None:
    png = with_before_idat(
        make_png(PORTRAIT),
        (b"eXIf", one_tag_tiff(ORIENTATION, 3, count=1000, value=b"\x00\x00\x01\x00")),
    )
    with pytest.raises(JpegExifError):
        set_orientation(png, 6)


def test_a_result_that_cannot_be_confirmed_is_never_returned(monkeypatch) -> None:
    monkeypatch.setattr(png_exif, "read_orientation", lambda *a, **k: 1)
    with pytest.raises(JpegExifError):
        set_orientation(make_png(PORTRAIT), 6)


def test_a_non_png_is_refused() -> None:
    with pytest.raises(NotAPngError):
        Layout.of(b"\xff\xd8 not a png")


def test_a_result_pillow_reads_differently_is_never_returned(monkeypatch) -> None:
    unedited = make_png(PORTRAIT, exif=exif_bytes(1))
    monkeypatch.setattr(png_exif, "decoder_copy", lambda *args, **kwargs: unedited)
    with pytest.raises(JpegExifError):
        set_orientation(make_png(PORTRAIT), 6)
