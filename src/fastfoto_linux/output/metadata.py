"""EXIF and XMP metadata for written photos: dates, notes, album."""

import calendar
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from PIL import ExifTags, Image

from fastfoto_linux import __version__
from fastfoto_linux.output.errors import InvalidDateError, InvalidNotesError

MAX_NOTES_CHARS = 10_000
MIN_YEAR = 1
MAX_YEAR = 9999
MONTHS_PER_YEAR = 12
CREATOR_TOOL = f"fastfoto-linux {__version__}"

_DATE = re.compile(r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?")
_EXIF_CLOCK = "%Y:%m:%d %H:%M:%S"
# Control characters, lone surrogates and U+FFFE/U+FFFF cannot appear in XML 1.0 at all.
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
_REPLACEMENT = "�"
_XPACKET_BEGIN = b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
_XPACKET_END = b'\n<?xpacket end="w"?>'

_NS_X = "adobe:ns:meta/"
_NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_PHOTOSHOP = "http://ns.adobe.com/photoshop/1.0/"
_NS_XMP = "http://ns.adobe.com/xap/1.0/"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

for _prefix, _uri in (
    ("x", _NS_X),
    ("rdf", _NS_RDF),
    ("dc", _NS_DC),
    ("photoshop", _NS_PHOTOSHOP),
    ("xmp", _NS_XMP),
):
    ET.register_namespace(_prefix, _uri)


@dataclass(frozen=True)
class PhotoDate:
    """A photo date with year, year-month or full-day precision."""

    year: int
    month: int | None = None
    day: int | None = None

    def __post_init__(self) -> None:
        if not MIN_YEAR <= self.year <= MAX_YEAR:
            raise InvalidDateError(f"year must be {MIN_YEAR}-{MAX_YEAR}, got {self.year}")
        if self.month is None:
            if self.day is not None:
                raise InvalidDateError(f"day {self.day} was given without a month")
            return
        if not 1 <= self.month <= MONTHS_PER_YEAR:
            raise InvalidDateError(f"month must be 1-{MONTHS_PER_YEAR}, got {self.month}")
        days_in_month = calendar.monthrange(self.year, self.month)[1]
        if self.day is not None and not 1 <= self.day <= days_in_month:
            raise InvalidDateError(f"day {self.day} does not exist in {self.year}-{self.month:02d}")

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse ``1975``, ``1975-06`` or ``1975-06-14``."""
        match = _DATE.fullmatch(text.strip())
        if match is None:
            raise InvalidDateError(f"date {text!r} must look like 1975, 1975-06 or 1975-06-14")
        year, month, day = match.groups()
        return cls(int(year), int(month) if month else None, int(day) if day else None)

    def __str__(self) -> str:
        text = f"{self.year:04d}"
        if self.month is not None:
            text += f"-{self.month:02d}"
        if self.day is not None:
            text += f"-{self.day:02d}"
        return text

    @property
    def exif_datetime(self) -> str:
        """EXIF timestamp for the start of the period, e.g. ``1975:06:01 00:00:00``."""
        return f"{self.year:04d}:{self.month or 1:02d}:{self.day or 1:02d} 00:00:00"

    @property
    def first_day(self) -> tuple[int, int, int]:
        """(year, month, day) of the start of the period, for ordering."""
        return (self.year, self.month or 1, self.day or 1)


@dataclass(frozen=True)
class DateRange:
    """An inclusive range of photo dates, e.g. a decade; ends compare by their first day."""

    start: PhotoDate
    end: PhotoDate

    def __post_init__(self) -> None:
        if self.end.first_day < self.start.first_day:
            raise InvalidDateError(f"range end {self.end} is before its start {self.start}")

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse an ISO 8601 style interval such as ``1970/1979`` or ``1975-06/1975-08``."""
        start, separator, end = text.partition("/")
        if not separator:
            raise InvalidDateError(f"range {text!r} must look like 1970/1979")
        return cls(PhotoDate.parse(start), PhotoDate.parse(end))

    def __str__(self) -> str:
        return f"{self.start}/{self.end}"


@dataclass(frozen=True)
class PhotoMetadata:
    """Everything that goes into one written file's EXIF and XMP.

    ``album`` should be the already sanitised folder name, which keeps the XMP small.
    """

    scanned_at: datetime
    written_at: datetime
    album: str | None = None
    notes: str | None = None
    date: PhotoDate | DateRange | None = None

    def __post_init__(self) -> None:
        if self.notes is not None and len(self.notes) > MAX_NOTES_CHARS:
            raise InvalidNotesError(
                f"notes are {len(self.notes)} characters long; the limit is {MAX_NOTES_CHARS}"
            )

    @property
    def start_date(self) -> PhotoDate | None:
        return self.date.start if isinstance(self.date, DateRange) else self.date


def _exif_clock(moment: datetime) -> str:
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.strftime(_EXIF_CLOCK)


def _exif_ascii(text: str) -> str:
    """Transliterate to printable ASCII: EXIF ASCII tags cannot hold Unicode.

    Accents are dropped and characters with no ASCII form are omitted; the full text is kept
    in XMP. Pillow would otherwise silently write ``?`` for each such character.
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join("".join(char if char.isprintable() else " " for char in folded).split())


def build_exif(meta: PhotoMetadata) -> bytes:
    """EXIF segment payload: description, software, write time, photo date, scan time."""
    exif = Image.Exif()
    description = _exif_ascii(meta.notes) if meta.notes else ""
    if description:
        exif[ExifTags.Base.ImageDescription] = description
    exif[ExifTags.Base.Software] = CREATOR_TOOL
    exif[ExifTags.Base.DateTime] = _exif_clock(meta.written_at)
    exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
    if meta.start_date is not None:
        exif_ifd[ExifTags.Base.DateTimeOriginal] = meta.start_date.exif_datetime
    exif_ifd[ExifTags.Base.DateTimeDigitized] = _exif_clock(meta.scanned_at)
    return exif.tobytes()


def _xml_text(text: str) -> str:
    """Make untrusted text storable in XML: unify line ends, replace illegal characters."""
    return _XML_ILLEGAL.sub(_REPLACEMENT, text.replace("\r\n", "\n").replace("\r", "\n"))


def _qname(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def _text_element(parent: ET.Element, namespace: str, tag: str, text: str) -> ET.Element:
    element = ET.SubElement(parent, _qname(namespace, tag))
    element.text = text
    return element


def _rdf_item(parent: ET.Element, tag: str, container: str, text: str) -> ET.Element:
    """``<dc:tag><rdf:container><rdf:li>text</rdf:li></rdf:container></dc:tag>``."""
    holder = ET.SubElement(ET.SubElement(parent, _qname(_NS_DC, tag)), _qname(_NS_RDF, container))
    return _text_element(holder, _NS_RDF, "li", text)


def build_xmp(meta: PhotoMetadata) -> bytes:
    """XMP packet with full-fidelity notes, album, photo date and creator tool."""
    root = ET.Element(_qname(_NS_X, "xmpmeta"))
    rdf = ET.SubElement(root, _qname(_NS_RDF, "RDF"))
    about = {_qname(_NS_RDF, "about"): ""}
    description = ET.SubElement(rdf, _qname(_NS_RDF, "Description"), about)
    album = " ".join(_xml_text(meta.album).split()) if meta.album else ""
    if album:
        _rdf_item(description, "subject", "Bag", album)
    if meta.notes:
        item = _rdf_item(description, "description", "Alt", _xml_text(meta.notes))
        item.set(_XML_LANG, "x-default")
    if isinstance(meta.date, DateRange):
        _text_element(description, _NS_DC, "coverage", str(meta.date))
    if meta.start_date is not None:
        _text_element(description, _NS_PHOTOSHOP, "DateCreated", str(meta.start_date))
    _text_element(description, _NS_XMP, "CreatorTool", CREATOR_TOOL)
    return _XPACKET_BEGIN + ET.tostring(root, encoding="utf-8") + _XPACKET_END
