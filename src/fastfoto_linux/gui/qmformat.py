"""Read a compiled Qt translation file (``.qm``) in Python, and refuse what the app must not load.

Plain Python. The format is a 16-byte magic number followed by sections, each a tag byte, a
32-bit big-endian length and that many bytes. The messages section holds records of tagged
fields: a translation (UTF-16BE), the source text, the context and a comment, ended by an end tag.

Reading the file here, before Qt gets it, closes two gaps a ``.ts`` check cannot:

* a ``.qm`` may carry a *dependencies* section, which makes Qt load other catalogs by the paths it
  names; any such section is refused, as is every section this reader does not know;
* a ``.qm`` can differ from the ``.ts`` it was meant to be built from, so the translations in it
  are checked here for markup, control characters and placeholders.
"""

import re
from dataclasses import dataclass

MAGIC = bytes.fromhex("3cb86418caef9c95cd211cbf60a1bddd")
SECTION_CONTEXTS = 0x2F
SECTION_HASHES = 0x42
SECTION_MESSAGES = 0x69
SECTION_NUMERUS_RULES = 0x88
SECTION_DEPENDENCIES = 0x96
SECTION_LANGUAGE = 0xA7
_KNOWN_SECTIONS = {
    SECTION_CONTEXTS,
    SECTION_HASHES,
    SECTION_MESSAGES,
    SECTION_NUMERUS_RULES,
    SECTION_LANGUAGE,
}
TAG_END, TAG_TRANSLATION, TAG_SOURCE, TAG_CONTEXT, TAG_COMMENT = 1, 3, 6, 7, 8
_TEXT_TAGS = {TAG_TRANSLATION, TAG_SOURCE, TAG_CONTEXT, TAG_COMMENT}
_MARKUP = re.compile(r"[<>&]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PLACEHOLDER = re.compile(r"%(?:L?\d+|n)")
_HEAD = 5  # a tag byte and a 32-bit length


class CatalogError(ValueError):
    """The file is not a catalog the app may load."""


@dataclass(frozen=True)
class CatalogEntry:
    context: str
    source: str
    translation: str


def _sections(data: bytes) -> list[tuple[int, bytes]]:
    if not data.startswith(MAGIC):
        raise CatalogError("not a translation catalog")
    found = []
    offset = len(MAGIC)
    while offset < len(data):
        if offset + _HEAD > len(data):
            raise CatalogError("truncated section header")
        tag = data[offset]
        size = int.from_bytes(data[offset + 1 : offset + _HEAD], "big")
        end = offset + _HEAD + size
        if end > len(data):
            raise CatalogError("section longer than the file")
        if tag == SECTION_DEPENDENCIES:
            raise CatalogError("a catalog with a dependencies section is not loaded")
        if tag not in _KNOWN_SECTIONS:
            raise CatalogError("unknown section in the catalog")
        found.append((tag, data[offset + _HEAD : end]))
        offset = end
    return found


def _record_fields(block: bytes) -> list[dict[int, list[bytes]]]:
    records: list[dict[int, list[bytes]]] = []
    fields: dict[int, list[bytes]] = {}
    offset = 0
    while offset < len(block):
        tag = block[offset]
        offset += 1
        if tag == TAG_END:
            records.append(fields)
            fields = {}
            continue
        if tag not in _TEXT_TAGS or offset + 4 > len(block):
            raise CatalogError("unreadable message record")
        size = int.from_bytes(block[offset : offset + 4], "big")
        offset += 4
        if offset + size > len(block):
            raise CatalogError("message record longer than its section")
        fields.setdefault(tag, []).append(block[offset : offset + size])
        offset += size
    if fields:
        raise CatalogError("message record without an end")
    return records


def _text(raw: bytes, encoding: str) -> str:
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError as error:
        raise CatalogError("text that does not decode") from error


def _check_translation(source: str, translation: str) -> None:
    if _MARKUP.search(translation):
        raise CatalogError("a translation with markup characters")
    if _CONTROL.search(translation):
        raise CatalogError("a translation with a control character")
    if sorted(_PLACEHOLDER.findall(translation)) != sorted(_PLACEHOLDER.findall(source)):
        raise CatalogError("a translation whose placeholders differ from its source")


def read_catalog(data: bytes) -> tuple[CatalogEntry, ...]:
    """The messages of a catalog; raises ``CatalogError`` for anything the app must not load."""
    entries = []
    for tag, block in _sections(data):
        if tag != SECTION_MESSAGES:
            continue
        for fields in _record_fields(block):
            translations = fields.get(TAG_TRANSLATION, [])
            source = _text(fields.get(TAG_SOURCE, [b""])[0], "utf-8")
            context = _text(fields.get(TAG_CONTEXT, [b""])[0], "utf-8")
            if not translations or len(fields.get(TAG_SOURCE, [])) != 1:
                raise CatalogError("message record without a translation or a source")
            decoded = [_text(item, "utf-16-be") for item in translations]
            for translation in decoded:
                _check_translation(source, translation)
            entries.append(CatalogEntry(context, source, decoded[0]))
    return tuple(entries)
