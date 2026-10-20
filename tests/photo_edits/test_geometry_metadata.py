"""Generated geometry metadata must agree with canonical upright pixels."""

import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Event

import pytest
from PIL import ExifTags, Image

from fastfoto_linux.photo_edits import PhotoEditError, PhotoEditRecipe, load_source, save_edit
from tests.photo_edits.helpers import pixels

TIFF = "http://ns.adobe.com/tiff/1.0/"
EXIF = "http://ns.adobe.com/exif/1.0/"
DC = "http://purl.org/dc/elements/1.1/"
XMP = "http://ns.adobe.com/xap/1.0/"


def _write_source(
    path: Path, orientation: int, *, unit: int = 2, jfif: bool = True, xmp: bytes = b""
) -> None:
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = orientation
    exif[ExifTags.Base.XResolution] = 300 if unit == 2 else 100
    exif[ExifTags.Base.YResolution] = 600 if unit == 2 else 200
    exif[ExifTags.Base.ResolutionUnit] = unit
    exif[ExifTags.Base.ImageDescription] = "Preserve this synthetic description"
    Image.fromarray(pixels()).save(
        path, exif=exif, xmp=xmp, **({"dpi": (300, 600)} if jfif else {})
    )


@pytest.mark.parametrize("orientation", [5, 6, 7, 8])
def test_rotated_exif_and_jfif_resolution_agree(tmp_path: Path, orientation: int) -> None:
    path = tmp_path / "oriented.jpg"
    _write_source(path, orientation)
    original = path.read_bytes()
    source = load_source(path)
    saved = save_edit(source, PhotoEditRecipe(source), cancel=Event())
    with Image.open(saved.image) as derivative:
        exif = derivative.getexif()
        assert exif[ExifTags.Base.Orientation] == 1
        assert float(exif[ExifTags.Base.XResolution]) == 600
        assert float(exif[ExifTags.Base.YResolution]) == 300
        assert exif[ExifTags.Base.ResolutionUnit] == 2
        assert derivative.info["dpi"] == (600, 300)
        assert exif[ExifTags.Base.ImageDescription] == "Preserve this synthetic description"
    assert path.read_bytes() == original


@pytest.mark.parametrize("unit,factor", [(2, 1.0), (3, 2.54)])
@pytest.mark.parametrize("orientation", [5, 6, 7, 8])
def test_exif_only_resolution_preserves_both_axes_and_units(
    tmp_path: Path, unit: int, factor: float, orientation: int
) -> None:
    path = tmp_path / "exif-resolution.jpg"
    _write_source(path, orientation, unit=unit, jfif=False)
    source = load_source(path)
    expected = (600, 300) if unit == 2 else (200 * factor, 100 * factor)
    assert (source.dpi_x, source.dpi_y) == pytest.approx(expected)
    saved = save_edit(source, PhotoEditRecipe(source), cancel=Event())
    with Image.open(saved.image) as image:
        exif = image.getexif()
        assert float(exif[ExifTags.Base.XResolution]) == pytest.approx(expected[0])
        assert float(exif[ExifTags.Base.YResolution]) == pytest.approx(expected[1])
        assert exif[ExifTags.Base.ResolutionUnit] == 2


def test_relative_resolution_has_no_absolute_dpi_and_uses_warned_fallback(tmp_path: Path) -> None:
    path = tmp_path / "relative-resolution.jpg"
    _write_source(path, 6, unit=1, jfif=False)
    source = load_source(path)
    assert (source.dpi_x, source.dpi_y) == (300, 300)
    assert source.warnings


def test_jfif_centimeter_units_are_converted_on_both_axes(tmp_path: Path) -> None:
    path = tmp_path / "jfif-cm.jpg"
    _write_source(path, 6, jfif=False)
    data = bytearray(path.read_bytes())
    marker = data.index(b"JFIF\x00")
    data[marker + 7] = 2
    data[marker + 8 : marker + 10] = (100).to_bytes(2, "big")
    data[marker + 10 : marker + 12] = (200).to_bytes(2, "big")
    path.write_bytes(data)
    source = load_source(path)
    assert (source.dpi_x, source.dpi_y) == pytest.approx((508, 254))


@pytest.mark.parametrize("as_attributes", [True, False])
@pytest.mark.parametrize("orientation", [5, 6, 7, 8])
def test_xmp_geometry_is_normalized_and_descriptive_metadata_survives(
    tmp_path: Path, orientation: int, as_attributes: bool
) -> None:
    path = tmp_path / "xmp.jpg"
    properties = {
        "tiff:Orientation": str(orientation),
        "tiff:XResolution": "300/1",
        "tiff:YResolution": "600/1",
        "tiff:ResolutionUnit": "2",
        "tiff:ImageWidth": "160",
        "tiff:ImageLength": "100",
        "exif:PixelXDimension": "160",
        "exif:PixelYDimension": "100",
    }
    attrs = " ".join(f'{key}="{value}"' for key, value in properties.items())
    elements = "".join(f"<{key}>{value}</{key}>" for key, value in properties.items())
    xmp = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        f'xmlns:tiff="{TIFF}" xmlns:exif="{EXIF}" xmlns:dc="{DC}" xmlns:xmp="{XMP}">'
        f"<rdf:RDF><rdf:Description {attrs if as_attributes else ''}>"
        f"{'' if as_attributes else elements}"
        "<dc:description>Keep the caption &amp; its punctuation</dc:description>"
        "<dc:subject><rdf:Bag><rdf:li>Synthetic album</rdf:li></rdf:Bag></dc:subject>"
        "<xmp:CreateDate>1975-06-01</xmp:CreateDate>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    ).encode()
    _write_source(path, orientation, xmp=xmp)
    source = load_source(path)
    saved = save_edit(source, PhotoEditRecipe(source), cancel=Event())
    with Image.open(saved.image) as image:
        root = ET.fromstring(image.info["xmp"])
    expected = {
        f"{{{TIFF}}}Orientation": "1",
        f"{{{TIFF}}}XResolution": "600/1",
        f"{{{TIFF}}}YResolution": "300/1",
        f"{{{TIFF}}}ResolutionUnit": "2",
        f"{{{TIFF}}}ImageWidth": "100",
        f"{{{TIFF}}}ImageLength": "160",
        f"{{{EXIF}}}PixelXDimension": "100",
        f"{{{EXIF}}}PixelYDimension": "160",
    }
    found = {}
    for element in root.iter():
        found.update({key: value for key, value in element.attrib.items() if key in expected})
        if element.tag in expected:
            found[element.tag] = element.text
    assert found == expected
    assert root.find(f".//{{{DC}}}description").text == "Keep the caption & its punctuation"
    assert root.find(f".//{{{XMP}}}CreateDate").text == "1975-06-01"
    assert "Synthetic album" in "".join(root.itertext())


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_xmp_document_types_and_entities_are_rejected_without_publication(
    tmp_path: Path, encoding: str
) -> None:
    path = tmp_path / "unsafe-xmp.jpg"
    xmp = (
        '<!DOCTYPE x [<!ENTITY external SYSTEM "https://example.invalid/do-not-read">]>'
        "<x>&external;</x>"
    ).encode(encoding)
    _write_source(path, 6, xmp=xmp)
    source = load_source(path)
    with pytest.raises(PhotoEditError, match=r"XMP|metadata"):
        save_edit(source, PhotoEditRecipe(source), cancel=Event())
    assert not list(tmp_path.glob("*_edit-*"))


@pytest.mark.parametrize("xmp", [b"<broken>", b"<x>&undefined;</x>"])
def test_malformed_xmp_cancels_save_with_a_clear_error(tmp_path: Path, xmp: bytes) -> None:
    path = tmp_path / "malformed-xmp.jpg"
    _write_source(path, 6, xmp=xmp)
    original = path.read_bytes()
    source = load_source(path)
    with pytest.raises(PhotoEditError, match="XMP metadata is malformed or unsupported"):
        save_edit(source, PhotoEditRecipe(source), cancel=Event())
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*_edit-*"))


@pytest.mark.parametrize("orientation", [5, 6, 7, 8])
def test_xmp_centimeter_resolution_is_rewritten_to_canonical_inches(
    tmp_path: Path, orientation: int
) -> None:
    path = tmp_path / "xmp-cm.jpg"
    xmp = (
        f'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:tiff="{TIFF}" '
        'tiff:ResolutionUnit="3" tiff:XResolution="100/1" tiff:YResolution="200/1"/>'
    ).encode()
    _write_source(path, orientation, unit=3, jfif=False, xmp=xmp)
    source = load_source(path)
    saved = save_edit(source, PhotoEditRecipe(source), cancel=Event())
    with Image.open(saved.image) as image:
        root = ET.fromstring(image.info["xmp"])
    assert root.attrib[f"{{{TIFF}}}ResolutionUnit"] == "2"
    assert root.attrib[f"{{{TIFF}}}XResolution"] == "508/1"
    assert root.attrib[f"{{{TIFF}}}YResolution"] == "254/1"
