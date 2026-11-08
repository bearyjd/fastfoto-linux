"""A conservative check of an XMP packet for an Orientation, shared by the JPEG and PNG paths.

An XMP Orientation (``tiff:Orientation``) the packet carries would disagree with the Exif tag
once that is changed, and a viewer may obey the wrong one. The packet is untrusted XML: the tiff
namespace can be bound to any prefix, spelled with character references or entities, and the
element can be written as an attribute. A byte scan cannot resolve those, and no XML parser with
entity expansion is wanted, so the namespace is not looked at at all: any ``Orientation`` element
or attribute, under any prefix or none, counts, and so do a packet that has NUL bytes (UTF-16, or
damaged) and one too large to scan. A false alarm only skips a file.
"""

import re

MAX_XMP_BYTES = 4 * 1024 * 1024  # a packet is scanned up to this size; a larger one counts

# An XML name: ASCII word characters, ``.`` and ``-``, and any non-ASCII character (UTF-8 bytes
# from 0x80 on); a colon is not part of one.
_XML_NAME = rb"[\w.\x80-\xff-]+"
# Element ``<p:Orientation`` or attribute `` p:Orientation=`` (prefix optional); XML is case
# sensitive, but a lenient reader may not be, so the case is ignored.
_ANY_ORIENTATION = re.compile(
    rb"<(?:" + _XML_NAME + rb":)?Orientation(?=[\s/>])|\s(?:" + _XML_NAME + rb":)?Orientation\s*=",
    re.IGNORECASE,
)


def names_any_orientation(packet: bytes) -> bool:
    """Whether the XMP ``packet`` might name an Orientation, however it spells the namespace."""
    if len(packet) > MAX_XMP_BYTES or b"\x00" in packet:
        return True
    return _ANY_ORIENTATION.search(packet) is not None
