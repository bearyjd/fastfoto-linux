"""Derivative metadata follows the geometry: output dimensions and swapped axes."""

import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Event

import pytest
from PIL import ExifTags, Image

from fastfoto_linux.photo_edits import PhotoGeometry, load_source, save_edit
from fastfoto_linux.photo_edits.metadata import derivative_exif, derivative_xmp
from tests.photo_edits.geometry_helpers import geometry_recipe
from tests.photo_edits.helpers import pixels

TIFF = "http://ns.adobe.com/tiff/1.0/"
EXIF = "http://ns.adobe.com/exif/1.0/"
XMP = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description rdf:about="" xmlns:tiff="http://ns.adobe.com/tiff/1.0/" '
    b'xmlns:exif="http://ns.adobe.com/exif/1.0/" tiff:Orientation="6" tiff:XResolution="300/1" '
    b'tiff:YResolution="600/1" tiff:ResolutionUnit="2" tiff:ImageWidth="160" '
    b'tiff:ImageLength="100" exif:PixelXDimension="160" exif:PixelYDimension="100"/>'
    b"</rdf:RDF></x:xmpmeta>"
)
# 600 dpi on one axis gives a 118 by 100 pixel minimum crop on the 160 by 100 image.
CROP = PhotoGeometry(1, (0, 0, 120, 100))


def _source(tmp_path: Path):
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 1
    exif[ExifTags.Base.XResolution] = 300
    exif[ExifTags.Base.YResolution] = 600
    exif[ExifTags.Base.ResolutionUnit] = 2
    exif[256], exif[257] = 160, 100
    details = exif.get_ifd(ExifTags.IFD.Exif)
    details[40962], details[40963] = 160, 100
    path = tmp_path / "photo.jpg"
    Image.fromarray(pixels()).save(path, exif=exif, xmp=XMP, dpi=(300, 600))
    return load_source(path)


def _attrs(data: bytes) -> dict[str, str]:
    description = next(e for e in ET.fromstring(data).iter() if e.tag.endswith("Description"))
    return {key.split("}")[1]: value for key, value in description.attrib.items() if "}" in key}


def test_exif_takes_output_dimensions_and_swapped_resolution(tmp_path: Path) -> None:
    exif = Image.Exif()
    exif.load(derivative_exif(_source(tmp_path), CROP))
    assert exif[ExifTags.Base.Orientation] == 1
    assert (float(exif[ExifTags.Base.XResolution]), float(exif[ExifTags.Base.YResolution])) == (
        600,
        300,
    )
    assert (exif[256], exif[257]) == (100, 120)
    details = exif.get_ifd(ExifTags.IFD.Exif)
    assert (details[40962], details[40963]) == (100, 120)


def test_even_turns_keep_the_axes_and_crop_dimensions(tmp_path: Path) -> None:
    exif = Image.Exif()
    exif.load(derivative_exif(_source(tmp_path), PhotoGeometry(2, (0, 0, 120, 100))))
    assert (float(exif[ExifTags.Base.XResolution]), float(exif[ExifTags.Base.YResolution])) == (
        300,
        600,
    )
    assert (exif[256], exif[257]) == (120, 100)


def test_default_geometry_keeps_todays_exif(tmp_path: Path) -> None:
    source = _source(tmp_path)
    assert derivative_exif(source) == derivative_exif(source, PhotoGeometry())
    exif = Image.Exif()
    exif.load(derivative_exif(source))
    assert (exif[256], exif[257]) == (160, 100)


def test_xmp_takes_output_dimensions_and_swapped_resolution(tmp_path: Path) -> None:
    attrs = _attrs(derivative_xmp(_source(tmp_path), CROP))
    assert (attrs["ImageWidth"], attrs["ImageLength"]) == ("100", "120")
    assert (attrs["PixelXDimension"], attrs["PixelYDimension"]) == ("100", "120")
    assert (attrs["XResolution"], attrs["YResolution"]) == ("600/1", "300/1")
    assert attrs["Orientation"] == "1"


def test_default_xmp_is_unchanged_in_content(tmp_path: Path) -> None:
    source = _source(tmp_path)
    assert derivative_xmp(source) == derivative_xmp(source, PhotoGeometry())
    assert _attrs(derivative_xmp(source))["ImageWidth"] == "160"


@pytest.mark.parametrize("turns", [1, 3])
def test_saved_file_has_upright_orientation_and_swapped_jfif_dpi(
    tmp_path: Path, turns: int
) -> None:
    source = _source(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(turns, (0, 0, 120, 100)))
    saved = save_edit(source, recipe, cancel=Event())
    with Image.open(saved.image) as derivative:
        exif = derivative.getexif()
        assert derivative.size == (100, 120)
        assert exif[ExifTags.Base.Orientation] == 1
        assert derivative.info["dpi"] == (600, 300)
        assert (float(exif[ExifTags.Base.XResolution]), float(exif[ExifTags.Base.YResolution])) == (
            600,
            300,
        )
        assert (exif[256], exif[257]) == (100, 120)
        assert 513 not in exif and 514 not in exif
