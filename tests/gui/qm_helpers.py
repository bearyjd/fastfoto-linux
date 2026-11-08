"""Build variants of the shipped German ``.qm`` file for the tests of the catalog checks."""

from fastfoto_linux.gui import i18n

HEADER = 16  # the magic number
SECTION_HEAD = 5  # a tag byte and a 32-bit length
DEPENDENCIES = 0x96
MESSAGES = 0x69


def shipped() -> bytes:
    path = i18n.catalog_path("de")
    assert path is not None
    return path.read_bytes()


def sections(data: bytes) -> list[tuple[int, bytes]]:
    found = []
    offset = HEADER
    while offset < len(data):
        size = int.from_bytes(data[offset + 1 : offset + SECTION_HEAD], "big")
        found.append((data[offset], data[offset + SECTION_HEAD : offset + SECTION_HEAD + size]))
        offset += SECTION_HEAD + size
    return found


def build(parts: list[tuple[int, bytes]], magic: bytes | None = None) -> bytes:
    body = b"".join(tag.to_bytes(1) + len(data).to_bytes(4, "big") + data for tag, data in parts)
    return (magic if magic is not None else shipped()[:HEADER]) + body


def with_dependency(catalog: str) -> bytes:
    """The shipped catalog plus a dependencies section naming ``catalog`` (Qt would load it)."""
    encoded = catalog.encode("utf-16-be")
    record = len(encoded).to_bytes(4, "big") + encoded
    parts = sections(shipped())
    return build([parts[0], (DEPENDENCIES, record), *parts[1:]])


def with_translation(old: str, new: str) -> bytes:
    """The shipped catalog with one translation replaced by a text of the same length."""
    assert len(old) == len(new)
    data = shipped()
    needle = old.encode("utf-16-be")
    assert data.count(needle) == 1
    return data.replace(needle, new.encode("utf-16-be"))
