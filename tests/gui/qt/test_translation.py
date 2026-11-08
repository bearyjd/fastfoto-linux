"""Loading the interface translation: only the packaged file, English on any failure."""

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QCoreApplication

from fastfoto_linux.gui import i18n
from fastfoto_linux.gui.qt import translation
from tests.gui import qm_helpers

pytestmark = pytest.mark.usefixtures("qapp")
GERMAN = "Scanner gefunden."


@pytest.fixture(autouse=True)
def english_again() -> Iterator[None]:
    """The application is shared by all tests: never leave a translator installed."""
    translation.deactivate()
    try:
        yield
    finally:
        translation.deactivate()


def finished_messages() -> list[tuple[str, str, str]]:
    root = ET.parse(i18n.source_path("de")).getroot()
    found = []
    for context in root.iter("context"):
        for message in context.iter("message"):
            node = message.find("translation")
            if node is not None and node.get("type") is None and node.text:
                found.append(
                    (context.findtext("name") or "", message.findtext("source"), node.text)
                )
    return found


def test_english_is_untouched_by_default() -> None:
    assert translation.active_code() == "en"
    assert translation.translate_message("Scanner found.") == "Scanner found."


def test_the_packaged_german_catalog_loads() -> None:
    assert translation.activate("de")
    assert translation.active_code() == "de"
    assert translation.translate_message("Scanner found.") == GERMAN


def test_every_finished_message_of_the_source_file_is_in_the_compiled_one() -> None:
    """A stale ``fastfoto_de.qm`` (the ``.ts`` edited, not recompiled) fails here."""
    assert translation.activate("de")
    messages = finished_messages()
    assert messages
    for context, source, expected in messages:
        assert QCoreApplication.translate(context, source) == expected, source


def test_a_message_without_a_translation_stays_as_it_is() -> None:
    assert translation.activate("de")
    assert translation.translate_message("A sentence nobody translated.") == (
        "A sentence nobody translated."
    )
    assert translation.translate_message("Scanning page 3") == "Scanning page 3"
    assert translation.translate_message("") == ""


def test_going_back_to_english_removes_the_translator() -> None:
    assert translation.activate("de")
    translation.deactivate()
    assert translation.active_code() == "en"
    assert translation.translate_message("Scanner found.") == "Scanner found."


def test_activating_twice_does_not_stack_translators() -> None:
    assert translation.activate("de")
    assert translation.activate("de")
    translation.deactivate()
    assert translation.translate_message("Scanner found.") == "Scanner found."


@pytest.mark.parametrize("code", ["en", "fr", "", "DE", "../de", "de/../de", None, 3])
def test_only_an_allowlisted_language_with_a_catalog_is_activated(code: Any) -> None:
    assert not translation.activate(code)
    assert translation.active_code() == "en"
    assert translation.translate_message("Scanner found.") == "Scanner found."


def test_a_catalog_in_the_working_directory_is_never_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "fastfoto_de.qm").write_bytes(b"decoy")
    (tmp_path / "translations").mkdir()
    (tmp_path / "translations" / "fastfoto_de.qm").write_bytes(b"decoy")
    monkeypatch.chdir(tmp_path)
    assert translation.activate("de")  # the packaged one, which is a real catalog
    assert translation.translate_message("Scanner found.") == GERMAN


def test_the_default_folder_is_the_packaged_one() -> None:
    assert translation.default_directory() == i18n.catalog_dir()


@pytest.mark.parametrize(
    "content",
    [b"", b"garbage", b"\x00" * 64, b"<!DOCTYPE TS><TS></TS>", bytes(range(256)) * 8],
    ids=["empty", "garbage", "zeros", "xml-not-qm", "noise"],
)
def test_a_corrupt_catalog_leaves_english(tmp_path: Path, content: bytes) -> None:
    (tmp_path / "fastfoto_de.qm").write_bytes(content)
    assert not translation.activate("de", directory=tmp_path)
    assert translation.active_code() == "en"
    assert translation.translate_message("Scanner found.") == "Scanner found."


def test_a_truncated_real_catalog_does_not_crash(tmp_path: Path) -> None:
    path = i18n.catalog_path("de")
    assert path is not None
    data = path.read_bytes()
    for cut in (4, 16, len(data) // 2, len(data) - 1):
        (tmp_path / "fastfoto_de.qm").write_bytes(data[:cut])
        translation.activate("de", directory=tmp_path)  # may load or not, but must not crash
        translation.translate_message("Scanner found.")
        translation.deactivate()


def test_a_missing_catalog_leaves_english(tmp_path: Path) -> None:
    assert not translation.activate("de", directory=tmp_path)
    assert translation.active_code() == "en"


def test_a_folder_in_place_of_the_catalog_leaves_english(tmp_path: Path) -> None:
    (tmp_path / "fastfoto_de.qm").mkdir()
    assert not translation.activate("de", directory=tmp_path)
    assert translation.active_code() == "en"


def test_a_catalog_over_the_size_limit_is_refused_unread(tmp_path: Path) -> None:
    path = i18n.catalog_path("de")
    assert path is not None
    big = tmp_path / "fastfoto_de.qm"
    big.write_bytes(path.read_bytes() + b"\x00" * translation.MAX_CATALOG_BYTES)
    assert not translation.activate("de", directory=tmp_path)
    assert translation.active_code() == "en"


def test_a_failed_activation_does_not_drop_the_language_that_was_active(tmp_path: Path) -> None:
    assert translation.activate("de")
    assert not translation.activate("de", directory=tmp_path)
    assert translation.active_code() == "de"
    assert translation.translate_message("Scanner found.") == GERMAN


def test_a_translation_is_text_not_a_format_string() -> None:
    """Whatever a translation contains comes back as it is: nothing is expanded or evaluated."""
    assert translation.activate("de")
    sample = "Scanner %1 {0} {name} %n"
    assert translation.translate_message(sample) == sample


def test_a_link_to_a_good_catalog_is_not_followed(tmp_path: Path) -> None:
    real = i18n.catalog_path("de")
    assert real is not None
    (tmp_path / "fastfoto_de.qm").symlink_to(real)
    assert not translation.activate("de", directory=tmp_path)
    assert translation.active_code() == "en"


def test_a_code_that_climbs_out_of_the_folder_never_reaches_a_good_catalog(tmp_path: Path) -> None:
    real = i18n.catalog_path("de")
    assert real is not None
    (tmp_path / "fastfoto_de.qm").write_bytes(real.read_bytes())
    (tmp_path / "fastfoto_x").mkdir()
    # fastfoto_<code>.qm with this code is fastfoto_x/../fastfoto_de.qm, the good file
    assert not translation.activate("x/../fastfoto_de", directory=tmp_path)
    assert translation.active_code() == "en"


@pytest.mark.parametrize("target", ["/etc/hostname", "../fastfoto_de", "other"])
def test_a_catalog_that_names_a_dependency_is_refused_not_followed(
    tmp_path: Path, target: str, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "fastfoto_de.qm").write_bytes(qm_helpers.with_dependency(target))
    assert not translation.activate("de", directory=tmp_path)
    assert translation.active_code() == "en"
    assert translation.translate_message("Scanner found.") == "Scanner found."
    assert str(tmp_path) not in caplog.text
    assert target not in caplog.text


def test_a_catalog_with_markup_added_after_compiling_is_refused() -> None:
    """The .ts checks cannot see a .qm edited by hand: the loader reads the .qm itself."""
    import tempfile

    with tempfile.TemporaryDirectory() as work:
        (Path(work) / "fastfoto_de.qm").write_bytes(qm_helpers.with_translation("Fotos", "<b>xx"))
        assert not translation.activate("de", directory=Path(work))
    assert translation.active_code() == "en"


def test_a_symlinked_folder_above_the_catalog_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "fastfoto_de.qm").write_bytes(qm_helpers.shipped())
    (tmp_path / "link").symlink_to(real)
    assert translation.activate("de", directory=real)
    translation.deactivate()
    assert not translation.activate("de", directory=tmp_path / "link")
    assert not translation.activate("de", directory=tmp_path / "link" / ".." / "real")
    assert translation.active_code() == "en"


def test_the_catalog_is_read_through_the_descriptor_it_was_checked_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file swapped in after the check is never loaded: the bytes read are the bytes loaded."""
    (tmp_path / "fastfoto_de.qm").write_bytes(qm_helpers.shipped())
    opened: list[int] = []
    real_open = translation.os.open

    def spy(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        opened.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(translation.os, "open", spy)
    assert translation.activate("de", directory=tmp_path)
    assert opened
    assert opened[-1] & translation.os.O_NOFOLLOW
    assert opened[-1] & translation.os.O_CLOEXEC


def test_unfinished_and_absent_messages_have_no_translation_at_run_time() -> None:
    assert translation.activate("de")
    root = ET.parse(i18n.source_path("de")).getroot()
    unfinished = 0
    for context in root.iter("context"):
        for message in context.iter("message"):
            node = message.find("translation")
            if node is not None and node.get("type") == "unfinished":
                unfinished += 1
                source = message.findtext("source")
                # a source can be finished in another context; ask in this one
                got = QCoreApplication.translate(context.findtext("name"), source)
                assert got == source, (context.findtext("name"), source)
    assert unfinished > 100
