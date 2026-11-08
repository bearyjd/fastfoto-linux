"""The structural check of a compiled catalog, and the guarantees that replace a semantic reader.

The loader does not read the messages of a ``.qm`` (Qt's own reader does that). It only walks the
section layout, which is where a malformed file can do harm. What the messages say is guaranteed
by the SHA-256 pin, by the byte-for-byte recompile of the reviewed ``.ts``, and by the tests of the
``.ts`` itself (``test_i18n.py``).
"""

import hashlib

import pytest

from fastfoto_linux.gui import i18n, qmformat
from tests.gui import qm_helpers

LANGUAGE, HASHES, MESSAGES, NUMERUS = 0xA7, 0x42, 0x69, 0x88


def refused(data: bytes, match: str) -> None:
    with pytest.raises(qmformat.CatalogError, match=match):
        qmformat.check_catalog(data)


def test_the_shipped_catalog_has_a_sound_structure() -> None:
    qmformat.check_catalog(qm_helpers.shipped())


def test_the_compiled_catalog_is_the_one_that_was_pinned() -> None:
    pin = i18n.pin_path("de").read_text().split()
    assert pin[1] == "fastfoto_de.qm"
    assert hashlib.sha256(qm_helpers.shipped()).hexdigest() == pin[0]


def test_a_catalog_edited_after_compiling_no_longer_matches_its_pin() -> None:
    """A compiled-only edit (markup, say) cannot pass the pin, whatever the loader checks."""
    pin = i18n.pin_path("de").read_text().split()[0]
    edited = qm_helpers.with_translation("Fotos", "<b>xx")
    assert hashlib.sha256(edited).hexdigest() != pin


def test_a_catalog_with_a_dependency_is_refused() -> None:
    for name in ("/etc/hostname", "../fastfoto_other", "other", "C:\\x"):
        refused(qm_helpers.with_dependency(name), "dependenc")


def test_an_unknown_section_is_refused() -> None:
    parts = qm_helpers.sections(qm_helpers.shipped())
    refused(qm_helpers.build([*parts, (0x55, b"x")]), "section")


def test_a_context_table_of_two_zero_bytes_is_refused() -> None:
    """The shape that made Qt divide by zero at the first lookup."""
    parts = qm_helpers.sections(qm_helpers.shipped())
    refused(qm_helpers.build([(0x2F, b"\x00\x00"), *parts]), "section")


def test_an_empty_or_misshapen_hash_table_is_refused() -> None:
    parts = dict(qm_helpers.sections(qm_helpers.shipped()))
    for table in (b"", b"\x00" * 4, b"\x00" * 7, parts[HASHES][:-1]):
        refused(
            qm_helpers.build(
                [(LANGUAGE, parts[LANGUAGE]), (HASHES, table), (MESSAGES, parts[MESSAGES])]
            ),
            "hash|empty",
        )


def test_a_zero_length_section_is_refused_wherever_it_is() -> None:
    parts = qm_helpers.sections(qm_helpers.shipped())
    for index in range(len(parts) + 1):
        broken = [*parts[:index], (LANGUAGE, b""), *parts[index:]]
        refused(qm_helpers.build(broken), "empty|order|twice")
    refused(
        qm_helpers.build([(tag, b"") if tag == NUMERUS else (tag, d) for tag, d in parts]), "empty"
    )


def test_sections_out_of_order_or_repeated_are_refused() -> None:
    parts = qm_helpers.sections(qm_helpers.shipped())
    refused(qm_helpers.build(list(reversed(parts))), "order")
    refused(qm_helpers.build([*parts, parts[0]]), "order|twice")
    refused(qm_helpers.build([parts[0], parts[0], *parts[1:]]), "twice")


def test_a_catalog_without_messages_or_hashes_is_refused() -> None:
    parts = qm_helpers.sections(qm_helpers.shipped())
    for dropped in (HASHES, MESSAGES):
        refused(qm_helpers.build([p for p in parts if p[0] != dropped]), "missing")


def test_a_wrong_magic_number_or_an_empty_file_is_refused() -> None:
    for data in (b"", b"x" * 16, b"\x00" * 100, qm_helpers.build([], magic=b"y" * 16)):
        refused(data, "catalog")


def test_every_truncation_is_refused_cleanly_never_with_another_error() -> None:
    data = qm_helpers.shipped()
    ends = {qm_helpers.HEADER}
    messages_end = 0
    for tag, payload in qm_helpers.sections(data):
        ends.add(max(ends) + qm_helpers.SECTION_HEAD + len(payload))
        if tag == MESSAGES:
            messages_end = max(ends)
    for cut in range(len(data)):
        if cut in ends and cut >= messages_end:
            continue  # ends after the messages: a shorter, well-formed catalog
        with pytest.raises(qmformat.CatalogError):
            qmformat.check_catalog(data[:cut])


def test_a_section_longer_than_the_file_is_refused() -> None:
    data = qm_helpers.shipped()
    broken = data[:16] + data[16:17] + (10**6).to_bytes(4, "big") + data[21:]
    refused(broken, "longer")


def test_bytes_after_the_last_section_are_refused() -> None:
    refused(qm_helpers.shipped() + b"\x00", "section|header|empty|order")
