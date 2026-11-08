"""Check the structure of a compiled Qt translation file (``.qm``) before Qt reads it.

Plain Python, and deliberately small. This does **not** read the messages: Qt does that, and a
partial re-implementation here would be a false security boundary. It only walks the section
layout, which is where a malformed file can do harm, and refuses what the app has no use for.

A file is a 16-byte magic number followed by sections, each a tag byte, a 32-bit big-endian length
and that many bytes. ``lrelease`` writes them in a fixed order: language, hashes, messages and the
numerus rules. A file must have exactly that shape:

* the sections follow one another, end to end, and the last one ends at the end of the file;
* every section is known, is not empty, appears at most once and is in that order (a zero-length
  section makes Qt stop reading there, so a good-looking catalog behind it is never loaded);
* the hash table, which Qt divides by its record size at the first lookup, is a whole number of
  records;
* the *dependencies* section, with which Qt loads other catalogs by path, is refused, and so is
  the context table (a two-byte one made Qt divide by zero).

What the messages say is not checked here. The compiled file is trusted for the same reasons as
the rest of the package: it is the packaged file, its SHA-256 is pinned, and it is byte-identical
to a fresh ``lrelease -nounfinished`` of the reviewed ``.ts`` (see ``docs/translating.md``).
"""

MAGIC = bytes.fromhex("3cb86418caef9c95cd211cbf60a1bddd")
SECTION_HASHES = 0x42
SECTION_MESSAGES = 0x69
SECTION_NUMERUS_RULES = 0x88
SECTION_DEPENDENCIES = 0x96
SECTION_LANGUAGE = 0xA7
_ORDER = (SECTION_LANGUAGE, SECTION_HASHES, SECTION_MESSAGES, SECTION_NUMERUS_RULES)
_REQUIRED = (SECTION_HASHES, SECTION_MESSAGES)
_HEAD = 5  # a tag byte and a 32-bit length
_HASH_RECORD = 8  # a 32-bit hash and a 32-bit offset


class CatalogError(ValueError):
    """The file is not a catalog the app may load."""


def check_catalog(data: bytes) -> None:
    """Raise ``CatalogError`` unless ``data`` has the layout of a catalog ``lrelease`` writes."""
    if not data.startswith(MAGIC):
        raise CatalogError("not a translation catalog")
    seen: list[int] = []
    offset = len(MAGIC)
    while offset < len(data):
        if offset + _HEAD > len(data):
            raise CatalogError("truncated section header")
        tag = data[offset]
        size = int.from_bytes(data[offset + 1 : offset + _HEAD], "big")
        if offset + _HEAD + size > len(data):
            raise CatalogError("section longer than the file")
        _check_section(tag, size, seen)
        seen.append(tag)
        offset += _HEAD + size
    for tag in _REQUIRED:
        if tag not in seen:
            raise CatalogError("a required section is missing")


def _check_section(tag: int, size: int, seen: list[int]) -> None:
    if tag == SECTION_DEPENDENCIES:
        raise CatalogError("a catalog with a dependencies section is not loaded")
    if tag not in _ORDER:
        raise CatalogError("unknown section in the catalog")
    if size == 0:
        raise CatalogError("empty section in the catalog")
    if tag in seen:
        raise CatalogError("a section appears twice")
    if seen and _ORDER.index(tag) < _ORDER.index(seen[-1]):
        raise CatalogError("sections out of order")
    if tag == SECTION_HASHES and size % _HASH_RECORD:
        raise CatalogError("hash table is not a whole number of records")
