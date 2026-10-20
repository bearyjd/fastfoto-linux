"""Canonical derivative geometry without changing descriptive source metadata."""

import xml.etree.ElementTree as ET
from fractions import Fraction

from PIL import ExifTags, Image

from fastfoto_linux.photo_edits.model import PhotoEditError, PhotoSource

EXIF_THUMBNAIL_KEYS = (513, 514)
RESOLUTION_UNIT_INCHES = 2
MAX_RATIONAL_DENOMINATOR = 1_000_000
TIFF_NS = "http://ns.adobe.com/tiff/1.0/"
EXIF_NS = "http://ns.adobe.com/exif/1.0/"


def derivative_exif(source: PhotoSource) -> bytes:
    """Match EXIF geometry and physical axes to the already upright source pixels."""
    exif = Image.Exif()
    if source.exif:
        exif.load(source.exif)
    exif[ExifTags.Base.Orientation] = 1
    exif[ExifTags.Base.XResolution] = source.dpi_x
    exif[ExifTags.Base.YResolution] = source.dpi_y
    exif[ExifTags.Base.ResolutionUnit] = RESOLUTION_UNIT_INCHES
    for key in EXIF_THUMBNAIL_KEYS:
        exif.pop(key, None)
    for key, value in ((256, source.width), (257, source.height)):
        if key in exif:
            exif[key] = value
    details = exif.get_ifd(ExifTags.IFD.Exif)
    for key, value in ((40962, source.width), (40963, source.height)):
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


def _geometry(source: PhotoSource) -> dict[str, str]:
    return {
        f"{{{TIFF_NS}}}Orientation": "1",
        f"{{{TIFF_NS}}}XResolution": _rational(source.dpi_x),
        f"{{{TIFF_NS}}}YResolution": _rational(source.dpi_y),
        f"{{{TIFF_NS}}}ResolutionUnit": str(RESOLUTION_UNIT_INCHES),
        f"{{{TIFF_NS}}}ImageWidth": str(source.width),
        f"{{{TIFF_NS}}}ImageLength": str(source.height),
        f"{{{EXIF_NS}}}PixelXDimension": str(source.width),
        f"{{{EXIF_NS}}}PixelYDimension": str(source.height),
    }


def derivative_xmp(source: PhotoSource) -> bytes:
    """Normalize present geometry fields; preserve descriptive metadata and safe packets."""
    if not source.xmp:
        return b""
    try:
        parser = ET.XMLParser(target=_SafeXmpBuilder(insert_comments=True, insert_pis=True))
        root = ET.fromstring(source.xmp, parser=parser)
        changed = False
        geometry = _geometry(source)
        for element in root.iter():
            for key in element.attrib.keys() & geometry.keys():
                element.set(key, geometry[key])
                changed = True
            if element.tag in geometry:
                value = geometry[element.tag]
                element.clear()
                element.text = value
                changed = True
        return ET.tostring(root, encoding="utf-8") if changed else source.xmp
    except (ET.ParseError, LookupError, RecursionError) as error:
        raise PhotoEditError(
            "XMP metadata is malformed or unsupported; Save was cancelled"
        ) from error
