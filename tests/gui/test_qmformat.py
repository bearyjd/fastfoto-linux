"""Reading a compiled catalog in Python: what is in it, and what is refused."""

import hashlib
import xml.etree.ElementTree as ET

import pytest

from fastfoto_linux.gui import i18n, qmformat
from tests.gui import qm_helpers


def finished() -> set[tuple[str, str, str]]:
    root = ET.parse(i18n.source_path("de")).getroot()
    found = set()
    for context in root.iter("context"):
        for message in context.iter("message"):
            node = message.find("translation")
            if node is not None and node.get("type") is None and node.text:
                found.add((context.findtext("name"), message.findtext("source"), node.text))
    return found


def test_the_compiled_catalog_holds_exactly_the_finished_messages_of_the_source_file() -> None:
    """Both ways: nothing unfinished ships, and nothing is in the .qm that the .ts lacks."""
    entries = qmformat.read_catalog(qm_helpers.shipped())
    assert {(e.context, e.source, e.translation) for e in entries} == finished()
    assert len(entries) == len(finished())


def test_the_compiled_catalog_is_the_one_that_was_pinned() -> None:
    pin = i18n.pin_path("de").read_text().split()
    assert pin[1] == "fastfoto_de.qm"
    assert hashlib.sha256(qm_helpers.shipped()).hexdigest() == pin[0]


def test_a_catalog_with_a_dependency_is_refused() -> None:
    for name in ("/etc/hostname", "../fastfoto_other", "other", "C:\\x"):
        with pytest.raises(qmformat.CatalogError, match="dependenc"):
            qmformat.read_catalog(qm_helpers.with_dependency(name))


def test_the_marked_up_translation_a_compiled_only_edit_could_add_is_refused() -> None:
    data = qm_helpers.with_translation("Fotos", "<b>xx")
    with pytest.raises(qmformat.CatalogError, match="markup"):
        qmformat.read_catalog(data)


@pytest.mark.parametrize("text", ["a&b__", "x>yzw", "ab\x01cd"])
def test_an_ampersand_a_bracket_or_a_control_character_is_refused(text: str) -> None:
    with pytest.raises(qmformat.CatalogError):
        qmformat.read_catalog(qm_helpers.with_translation("Fotos", text[:5].ljust(5, "_")))


def test_a_translation_with_other_placeholders_than_its_source_is_refused() -> None:
    parts = qm_helpers.sections(qm_helpers.shipped())
    data = qm_helpers.with_translation("Fotos", "Fo%1s")  # "Photos" has no placeholder
    assert data != qm_helpers.shipped()
    assert len(parts) >= 3
    with pytest.raises(qmformat.CatalogError, match="placeholder"):
        qmformat.read_catalog(data)


def test_an_unknown_section_is_refused() -> None:
    parts = qm_helpers.sections(qm_helpers.shipped())
    with pytest.raises(qmformat.CatalogError, match="section"):
        qmformat.read_catalog(qm_helpers.build([*parts, (0x55, b"x")]))


def test_a_wrong_magic_number_or_an_empty_file_is_refused() -> None:
    for data in (b"", b"x" * 16, b"\x00" * 100, qm_helpers.build([], magic=b"y" * 16)):
        with pytest.raises(qmformat.CatalogError):
            qmformat.read_catalog(data)


def test_every_truncation_is_refused_cleanly_never_with_another_error() -> None:
    data = qm_helpers.shipped()
    boundaries = {qm_helpers.HEADER}
    for _tag, payload in qm_helpers.sections(data):
        boundaries.add(max(boundaries) + qm_helpers.SECTION_HEAD + len(payload))
    for cut in range(len(data)):
        if cut in boundaries:
            continue  # ends between two sections: a shorter, well-formed catalog
        with pytest.raises(qmformat.CatalogError):
            qmformat.read_catalog(data[:cut])


def test_a_section_longer_than_the_file_is_refused() -> None:
    data = qm_helpers.shipped()
    broken = data[:16] + data[16:17] + (10**6).to_bytes(4, "big") + data[21:]
    with pytest.raises(qmformat.CatalogError):
        qmformat.read_catalog(broken)
