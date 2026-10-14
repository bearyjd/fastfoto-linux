"""EXIF and XMP metadata for written photos: dates, notes, album."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Self
from xml.sax.saxutils import escape

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
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_REPLACEMENT = "\ufffd"
_XPACKET_BEGIN = b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
_XPACKET_END = b'\n<?xpacket end="w"?>'

_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_PHOTOSHOP = "http://ns.adobe.com/photoshop/1.0/"
_NS_XMP = "http://ns.adobe.com/xap/1.0/"
# The packet is written out by hand with these fixed prefixes (every value is escaped), rather
# than through xml.etree, whose namespace prefixes are a process-wide registry.
_XMP_HEAD = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    f'<rdf:Description rdf:about="" xmlns:dc="{_NS_DC}"'
    f' xmlns:photoshop="{_NS_PHOTOSHOP}" xmlns:xmp="{_NS_XMP}">'
)
_XMP_TAIL = "</rdf:Description></rdf:RDF></x:xmpmeta>"


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
    def first_day(self) -> date:
        """First day the date can mean: ``1975`` is 1975-01-01, ``1975-06`` is 1975-06-01."""
        return date(self.year, self.month or 1, self.day or 1)

    @property
    def last_day(self) -> date:
        """Last day the date can mean: ``1975`` is 1975-12-31, ``1975-06`` is 1975-06-30."""
        month = self.month or MONTHS_PER_YEAR
        return date(self.year, month, self.day or calendar.monthrange(self.year, month)[1])


@dataclass(frozen=True)
class DateRange:
    """An inclusive range of photo dates, e.g. a decade.

    A partial date stands for every day it covers, so ``1975-06/1975`` is fine (June to the end
    of 1975); only an end that lies wholly before the start is rejected.
    """

    start: PhotoDate
    end: PhotoDate

    def __post_init__(self) -> None:
        if self.end.last_day < self.start.first_day:
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


def build_exif(meta: PhotoMetadata) -> bytes:
    """EXIF segment payload: description, software, write time, photo date, scan time.

    ``ImageDescription`` is an ASCII tag, so it carries the notes only when they are already
    printable ASCII. Anything else (accents, other scripts, line breaks) is left out rather
    than transliterated, which would change what it says; XMP always has the full text.
    """
    exif = Image.Exif()
    if meta.notes and meta.notes.isascii() and meta.notes.isprintable():
        exif[ExifTags.Base.ImageDescription] = meta.notes
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


def _leaf(tag: str, text: str, attributes: str = "") -> str:
    return f"<{tag}{attributes}>{escape(text)}</{tag}>"


def _rdf_item(tag: str, container: str, text: str, attributes: str = "") -> str:
    """``<dc:tag><rdf:container><rdf:li>text</rdf:li></rdf:container></dc:tag>``."""
    return f"<{tag}><rdf:{container}>{_leaf('rdf:li', text, attributes)}</rdf:{container}></{tag}>"


def build_xmp(meta: PhotoMetadata) -> bytes:
    """XMP packet with full-fidelity notes, album, photo date and creator tool.

    All text is escaped and stripped of characters XML cannot hold, so notes and album names
    can contain anything without breaking the packet.
    """
    parts = [_XMP_HEAD]
    album = " ".join(_xml_text(meta.album).split()) if meta.album else ""
    if album:
        parts.append(_rdf_item("dc:subject", "Bag", album))
    if meta.notes:
        notes = _xml_text(meta.notes)
        parts.append(_rdf_item("dc:description", "Alt", notes, ' xml:lang="x-default"'))
    if isinstance(meta.date, DateRange):
        parts.append(_leaf("dc:coverage", str(meta.date)))
    if meta.start_date is not None:
        parts.append(_leaf("photoshop:DateCreated", str(meta.start_date)))
    parts.extend([_leaf("xmp:CreatorTool", CREATOR_TOOL), _XMP_TAIL])
    return _XPACKET_BEGIN + "".join(parts).encode("utf-8") + _XPACKET_END
