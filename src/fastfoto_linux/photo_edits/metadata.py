"""Canonical derivative geometry without changing descriptive source metadata."""

import xml.etree.ElementTree as ET
from fractions import Fraction

from PIL import ExifTags, Image

from fastfoto_linux.photo_edits.geometry import output_size
from fastfoto_linux.photo_edits.model import PhotoEditError, PhotoGeometry, PhotoSource

EXIF_THUMBNAIL_KEYS = (513, 514)
RESOLUTION_UNIT_INCHES = 2
MAX_RATIONAL_DENOMINATOR = 1_000_000
NEUTRAL_GEOMETRY = PhotoGeometry()
TIFF_NS = "http://ns.adobe.com/tiff/1.0/"
EXIF_NS = "http://ns.adobe.com/exif/1.0/"


def frame(source: PhotoSource, geometry: PhotoGeometry) -> tuple[int, int, float, float]:
    """Output width, height and per-axis DPI; odd quarter turns swap the physical axes."""
    width, height = output_size(source, geometry)
    if geometry.quarter_turns % 2:
        return width, height, source.dpi_y, source.dpi_x
    return width, height, source.dpi_x, source.dpi_y


def derivative_exif(source: PhotoSource, geometry: PhotoGeometry = NEUTRAL_GEOMETRY) -> bytes:
    """Match EXIF geometry and physical axes to the upright output pixels."""
    width, height, dpi_x, dpi_y = frame(source, geometry)
    exif = Image.Exif()
    if source.exif:
        exif.load(source.exif)
    exif[ExifTags.Base.Orientation] = 1
    exif[ExifTags.Base.XResolution] = dpi_x
    exif[ExifTags.Base.YResolution] = dpi_y
    exif[ExifTags.Base.ResolutionUnit] = RESOLUTION_UNIT_INCHES
    for key in EXIF_THUMBNAIL_KEYS:
        exif.pop(key, None)
    for key, value in ((256, width), (257, height)):
        if key in exif:
            exif[key] = value
    details = exif.get_ifd(ExifTags.IFD.Exif)
    for key, value in ((40962, width), (40963, height)):
        if key in details:
            details[key] = value
    return exif.tobytes()


class _SafeXmpBuilder(ET.TreeBuilder):
    """XMP needs no DTD; reject declarations rather than resolve external resources."""

    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise PhotoEditError("XMP document types and entity declarations are unsupported")


def _rational(value: float) -> str:
    fraction = Fraction(str(value)).limit_denominator(MAX_RATIONAL_DENOMINATOR)
    return f"{fraction.numerator}/{fraction.denominator}"


def _geometry(source: PhotoSource, geometry: PhotoGeometry) -> dict[str, str]:
    width, height, dpi_x, dpi_y = frame(source, geometry)
    return {
        f"{{{TIFF_NS}}}Orientation": "1",
        f"{{{TIFF_NS}}}XResolution": _rational(dpi_x),
        f"{{{TIFF_NS}}}YResolution": _rational(dpi_y),
        f"{{{TIFF_NS}}}ResolutionUnit": str(RESOLUTION_UNIT_INCHES),
        f"{{{TIFF_NS}}}ImageWidth": str(width),
        f"{{{TIFF_NS}}}ImageLength": str(height),
        f"{{{EXIF_NS}}}PixelXDimension": str(width),
        f"{{{EXIF_NS}}}PixelYDimension": str(height),
    }


def derivative_xmp(source: PhotoSource, geometry: PhotoGeometry = NEUTRAL_GEOMETRY) -> bytes:
    """Normalize present geometry fields; preserve descriptive metadata and safe packets."""
    if not source.xmp:
        return b""
    try:
        parser = ET.XMLParser(target=_SafeXmpBuilder(insert_comments=True, insert_pis=True))
        root = ET.fromstring(source.xmp, parser=parser)
        changed = False
        fields = _geometry(source, geometry)
        for element in root.iter():
            for key in element.attrib.keys() & fields.keys():
                element.set(key, fields[key])
                changed = True
            if element.tag in fields:
                value = fields[element.tag]
                element.clear()
                element.text = value
                changed = True
        return ET.tostring(root, encoding="utf-8") if changed else source.xmp
    except (ET.ParseError, LookupError, RecursionError) as error:
        raise PhotoEditError(
            "XMP metadata is malformed or unsupported; Save was cancelled"
        ) from error
