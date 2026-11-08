"""The interface language: which codes exist, the marker, the shipped catalog files."""

import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fastfoto_linux.gui import form, i18n, report

PLACEHOLDER = re.compile(r"%(?:L?\d+|n)")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def messages() -> list[tuple[str, str, str, str | None]]:
    """(context, source, translation, type) of every message of the German catalog."""
    root = ET.parse(i18n.source_path("de")).getroot()
    found = []
    for context in root.iter("context"):
        for message in context.iter("message"):
            translation = message.find("translation")
            assert translation is not None
            found.append(
                (
                    context.findtext("name") or "",
                    message.findtext("source") or "",
                    translation.text or "",
                    translation.get("type"),
                )
            )
    return found


def test_the_marker_returns_the_text_unchanged() -> None:
    assert i18n.QT_TRANSLATE_NOOP("messages", "Scanner found.") == "Scanner found."


def test_english_is_the_default_and_german_the_only_other_language() -> None:
    assert i18n.DEFAULT_LANGUAGE == "en"
    assert [language.code for language in i18n.UI_LANGUAGES] == ["en", "de"]


def test_german_is_marked_partial_and_english_is_not() -> None:
    by_code = {language.code: language for language in i18n.UI_LANGUAGES}
    assert by_code["de"].partial
    assert "partial" in by_code["de"].label.lower()
    assert not by_code["en"].partial
    assert "partial" not in by_code["en"].label.lower()


@pytest.mark.parametrize("code", ["en", "de"])
def test_a_known_code_is_kept(code: str) -> None:
    assert i18n.ui_language_code(code) == code


@pytest.mark.parametrize(
    "value",
    ["", "DE", "de ", "fr", "deu", "../de", "de/../en", "/etc/passwd", "de\x00", None, 5, ["de"]],
)
def test_anything_else_is_english(value: object) -> None:
    assert i18n.ui_language_code(value) == "en"


def test_the_catalog_of_english_does_not_exist() -> None:
    assert i18n.catalog_path("en") is None
    assert i18n.catalog_path("../de") is None


def test_the_german_catalog_ships_with_the_package() -> None:
    path = i18n.catalog_path("de")
    assert path is not None
    assert path.is_file()
    assert path.name == "fastfoto_de.qm"
    assert path.parent == i18n.catalog_dir()
    assert path.parent.parts[-3:] == ("fastfoto_linux", "gui", "translations")


def test_the_german_source_file_is_next_to_the_compiled_one() -> None:
    assert i18n.source_path("de").is_file()
    assert i18n.source_path("de").parent == i18n.catalog_dir()


def test_the_german_catalog_names_its_language_and_has_some_finished_messages() -> None:
    root = ET.parse(i18n.source_path("de")).getroot()
    assert root.get("language") == "de"
    finished = [item for item in messages() if item[3] is None and item[2]]
    assert len(finished) >= 10


def test_the_german_catalog_is_partial_not_complete() -> None:
    unfinished = [item for item in messages() if item[3] == "unfinished"]
    assert unfinished, "the pilot is partial: untranslated messages stay listed as unfinished"


def test_every_translation_has_the_placeholders_of_its_source() -> None:
    for _, source, translation, kind in messages():
        if kind is None:
            assert sorted(PLACEHOLDER.findall(translation)) == sorted(
                PLACEHOLDER.findall(source)
            ), source


def test_no_translation_has_markup_an_ampersand_or_a_control_character() -> None:
    for _, source, translation, _kind in messages():
        assert not re.search(r"[<>&]", translation), source
        assert not CONTROL.search(translation), source


def test_no_translation_is_empty_or_blank_when_finished() -> None:
    for _, source, translation, kind in messages():
        if kind is None:
            assert translation.strip(), source


def test_every_translation_keeps_the_end_of_its_sentence() -> None:
    """A source that ends in a full stop or an ellipsis is translated to one that does too."""
    for _, source, translation, kind in messages():
        if kind is None and source.endswith((".", "…")):
            assert translation.endswith((".", "…")), source


def test_the_marked_python_messages_stay_the_english_they_always_were() -> None:
    assert report.FOUND_TEXT == "Scanner found."
    assert report.CHECKING_TEXT == "Looking for the scanner…"
    assert report.CHECKING_SCANNER_TEXT == "Checking the scanner…"
    assert report.NOT_CHECKED == "The scanner has not been checked yet."
    assert report.NO_SCANNER_HINT == "Press Check again to look for the scanner."
    assert report.CANCELLING_TEXT == "Cancelling…"
    assert form.FOLDER_REQUIRED == "Choose the folder the photos are saved in."


def test_the_catalog_directory_is_not_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert i18n.catalog_dir().is_absolute()
    assert tmp_path not in i18n.catalog_dir().parents


def test_a_translated_python_message_is_not_longer_than_the_english_one() -> None:
    """These messages sit in the bar under the scan form, which has room for the English length.

    A longer one wraps and makes the bar taller, which squeezes the form above it (a longer label
    once displaced a form control that way).
    """
    for context, source, translation, kind in messages():
        if context == i18n.MESSAGES_CONTEXT and kind is None:
            assert len(translation) <= len(source) + 4, source


QML_DIR = Path(__file__).resolve().parents[2] / "src" / "fastfoto_linux" / "gui" / "qml"
TEXT_TYPES = r"(?<![\w.])(QQC2\.Label|Kirigami\.Heading|Kirigami\.SelectableLabel|Text)\s*\{"
PINNED_QT = "6.10.3"  # the Qt the committed .qm was compiled with


def own_properties(source: str, start: int) -> str:
    """The text of the block that opens just before ``start``, without its nested blocks."""
    depth, end = 1, start
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    block = source[start : end - 1]
    while (flat := re.sub(r"\{[^{}]*\}", "", block)) != block:
        block = flat
    return block


def test_every_label_and_heading_in_the_qml_shows_plain_text() -> None:
    """A translation is text, whatever it contains: no label may read it as rich text."""
    missing = []
    for qml in sorted(QML_DIR.glob("*.qml")):
        source = qml.read_text()
        for match in re.finditer(TEXT_TYPES, source):
            if "textFormat" not in own_properties(source, match.end()):
                missing.append(f"{qml.name}:{source[: match.start()].count(chr(10)) + 1}")
    # PhotoEditCanvas.qml draws marker glyphs, not translated text
    assert [name for name in missing if not name.startswith("PhotoEditCanvas.qml")] == []


def lrelease() -> str | None:
    return shutil.which("lrelease-qt6") or shutil.which("lrelease")


def lrelease_matches_the_pinned_qt() -> bool:
    tool = lrelease()
    if tool is None:
        return False
    done = subprocess.run([tool, "-version"], capture_output=True, text=True, check=False)
    return PINNED_QT in done.stdout + done.stderr


@pytest.mark.skipif(lrelease() is None, reason="Qt's lrelease (qt6-linguist) is not installed")
def test_the_compiled_catalog_is_what_lrelease_makes_of_the_source_file() -> None:
    """Only where lrelease exists (the required jobs have none; the pin test covers them)."""
    if not lrelease_matches_the_pinned_qt():
        pytest.skip(f"the committed .qm was compiled with Qt {PINNED_QT}; this lrelease differs")
    with tempfile.TemporaryDirectory() as work:
        target = Path(work) / "out.qm"
        source = str(i18n.source_path("de"))
        subprocess.run(
            [lrelease(), "-nounfinished", "-silent", source, "-qm", str(target)], check=True
        )
        assert target.read_bytes() == i18n.catalog_path("de").read_bytes()


def test_two_german_messages_read_as_the_state_they_describe() -> None:
    by_source = {source: translation for _, source, translation, _ in messages()}
    assert by_source["Cancelling…"] == "Abbruch läuft …"
    assert "Neu prüfen" in by_source["Press Check again to look for the scanner."]
