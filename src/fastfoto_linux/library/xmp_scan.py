"""A conservative check of an XMP packet for an Orientation, shared by the JPEG and PNG paths.

An XMP Orientation (``tiff:Orientation``) the packet carries would disagree with the Exif tag
once that is changed, and a viewer may obey the wrong one. The packet is untrusted XML. No XML
parser (and no entity expansion) is used: the packet is read as bytes by two linear regular
expressions, and anything that is not plainly ordinary XMP counts as an Orientation, because a
false alarm only skips a file. A packet counts when it:

* is over ``MAX_XMP_BYTES``, has a NUL byte (UTF-16, UTF-32) or starts like EBCDIC;
* has an XML declaration that is not at the very start, or names an encoding other than UTF-8
  (UTF-7, cp037 and the like hide names from a byte scan but not from a parser);
* is not made only of comments, CDATA sections, processing instructions and well-formed tags
  (quoted attribute values, ``name="..."``): this covers a DOCTYPE, ``<!ENTITY``, ``<!ATTLIST``
  (an entity can build a tag, a default attribute can supply one), unterminated quotes, tags or
  comments, unquoted values, and a character reference where a name should be;
* has a tag whose name, or an attribute whose name, has the local name ``Orientation`` under any
  prefix or none, in any case. The namespace is not looked at (it can be spelled in ways a byte
  scan cannot resolve), and neither are attribute values or text: a caption saying
  ``Orientation=portrait`` is no orientation. A tag need not be separated from the previous
  attribute by whitespace.

A comment, CDATA section, processing instruction or quoted attribute value is not markup to a
parser, but one holding something that looks like a tag named ``Orientation``
(``<tiff:Orientation>``, ``<a tiff:Orientation="1">``) also counts: a lenient reader might not
skip it, and a strict parser rejects a literal ``<`` in a value anyway. Other text in them, a
bare ``<`` included, is ignored.

Known fail-closed over-refusals (a false alarm only skips a file, and these are very rare):

* A packet with NUL bytes is skipped, even NUL-padded UTF-8 (the NULs cannot be told from UTF-16).
* An XML declaration is looked for anywhere, CDATA included, so a valid caption such as
  ``<dc:description><![CDATA[Camera Orientation: <?xml version="1.0"?>]]></dc:description>``
  is refused.
"""

import re

MAX_XMP_BYTES = 4 * 1024 * 1024  # a packet is scanned up to this size; a larger one counts

_EBCDIC_START = b"\x4c\x6f\xa7\x94"  # "<?xm" in EBCDIC: how a parser tells it is not ASCII
_BOM = b"\xef\xbb\xbf"

# Every pattern is linear: the repeats are possessive and no two neighbours can match the same
# bytes in more than one way. A name is ASCII word characters, ``.``, ``-``, ``:`` and any
# non-ASCII byte (UTF-8 bytes from 0x80 on); a character reference or ``+`` is not one.
_NAME = rb"[\w.\x80-\xff:-]++"
_VALUE = rb"(?:\"[^\"]*+\"|'[^']*+')"
_ATTRIBUTE = rb"\s*+" + _NAME + rb"\s*+=\s*+" + _VALUE
_CONSTRUCT = (
    rb"(?:<!--.*?-->"  # comment
    rb"|<!\[CDATA\[.*?\]\]>"
    rb"|<\?.*?\?>"  # processing instruction (an XML declaration is checked apart)
    rb"|</" + _NAME + rb"\s*+>"  # end tag
    rb"|<" + _NAME + rb"(?:" + _ATTRIBUTE + rb")*+\s*+/?>)"  # start tag
)
_WELL_FORMED = re.compile(rb"[^<]*+(?:" + _CONSTRUCT + rb"[^<]*+)*+", re.DOTALL)

# A name whose local part (after the last colon, if any) is Orientation.
_ORIENTATION = rb"(?:[\w.\x80-\xff:-]*:)?orientation(?![\w.\x80-\xff:-])"
_ORIENTATION_ELEMENT = rb"</?" + _ORIENTATION
_ORIENTATION_ATTRIBUTE = rb"<" + _NAME + rb"(?:" + _ATTRIBUTE + rb")*?\s*+" + _ORIENTATION
_ORIENTATION_TAG = re.compile(
    _ORIENTATION_ELEMENT + rb"|" + _ORIENTATION_ATTRIBUTE, re.IGNORECASE | re.DOTALL
)

_XML_DECLARATION = re.compile(
    rb"(?:\xef\xbb\xbf)?<\?xml(?=[\s?])(.*?)\?>", re.IGNORECASE | re.DOTALL
)
_XML_TARGET = re.compile(rb"<\?xml(?=[\s?])", re.IGNORECASE)
_ENCODING = re.compile(rb"\sencoding\s*=\s*([\"'])([^\"']*)\1", re.IGNORECASE)


def _foreign_declaration(packet: bytes) -> bool:
    """Whether an XML declaration is misplaced, or names an encoding that is not UTF-8."""
    declaration = _XML_DECLARATION.match(packet)
    if declaration is None:
        return _XML_TARGET.search(packet) is not None
    if _XML_TARGET.search(packet, declaration.end()) is not None:
        return True
    body = declaration[1]
    if re.search(rb"encoding", body, re.IGNORECASE) is None:
        return False
    named = _ENCODING.search(body)
    return named is None or named[2].lower() != b"utf-8"


def names_any_orientation(packet: bytes) -> bool:
    """Whether the XMP ``packet`` might name an Orientation, however it spells the namespace."""
    if len(packet) > MAX_XMP_BYTES or b"\x00" in packet or packet.startswith(_EBCDIC_START):
        return True
    if _foreign_declaration(packet) or _WELL_FORMED.fullmatch(packet) is None:
        return True
    return b"orientation" in packet.lower() and _ORIENTATION_TAG.search(packet) is not None
