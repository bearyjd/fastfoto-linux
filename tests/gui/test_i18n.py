"""The interface language: which codes exist, the marker, the shipped catalog files."""

import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fastfoto_linux.gui import form, i18n, report

PLACEHOLDER = re.compile(r"%L?(?:\d+|n)")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def messages() -> list[tuple[str, str, tuple[str, ...], str | None]]:
    """(context, source, every form of the translation, type) of each message of the German .ts.

    A message with plural forms has one text per ``<numerusform>``; any other has one text.
    """
    root = ET.parse(i18n.source_path("de")).getroot()
    found = []
    for context in root.iter("context"):
        for message in context.iter("message"):
            translation = message.find("translation")
            assert translation is not None
            forms = translation.findall("numerusform")
            texts = tuple(form.text or "" for form in forms) or (translation.text or "",)
            found.append(
                (
                    context.findtext("name") or "",
                    message.findtext("source") or "",
                    texts,
                    translation.get("type"),
                )
            )
    return found


def problems(source: str, forms: tuple[str, ...]) -> list[str]:
    """What is wrong with the forms of a translation; each one must pass every rule."""
    found = []
    for form_text in forms:
        if not form_text.strip():
            found.append("empty")
        if re.search(r"[<>&]", form_text):
            found.append("markup")
        if CONTROL.search(form_text):
            found.append("control character")
        if sorted(PLACEHOLDER.findall(form_text)) != sorted(PLACEHOLDER.findall(source)):
            found.append("placeholders")
        if source.endswith((".", "…")) and not form_text.endswith((".", "…")):
            found.append("sentence end")
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
    finished = [item for item in messages() if item[3] is None and any(item[2])]
    assert len(finished) >= 10


def test_the_german_catalog_is_partial_not_complete() -> None:
    unfinished = [item for item in messages() if item[3] == "unfinished"]
    assert unfinished, "the pilot is partial: untranslated messages stay listed as unfinished"


def test_every_finished_translation_passes_every_rule() -> None:
    """Markup, control characters, placeholders (%1..%9, %n, %Ln), blank text, sentence end."""
    for _, source, forms, kind in messages():
        if kind is None:
            assert problems(source, forms) == [], source


def test_unfinished_suggestions_are_free_of_markup_too() -> None:
    for _, source, forms, kind in messages():
        if kind == "unfinished" and any(forms):
            found = problems(source, tuple(text for text in forms if text))
            assert "markup" not in found and "control character" not in found, source


def test_the_rules_catch_each_kind_of_fault_in_any_plural_form() -> None:
    assert problems("Done.", ("Fertig.",)) == []
    assert problems("%n page(s)", ("%n Seite", "%n Seiten")) == []
    assert problems("%Ln file(s)", ("%Ln Datei", "%Ln Dateien")) == []
    assert "placeholders" in problems("%Ln file(s)", ("%Ln Datei", "%n Dateien"))
    assert "placeholders" in problems("%n page(s)", ("%n Seite", "Seiten"))
    assert "placeholders" in problems("About %1", ("Zu",))
    assert "placeholders" in problems("About", ("Zu %1",))
    assert "markup" in problems("Page", ("Seite", "<b>Seiten</b>"))
    assert "markup" in problems("Page", ("a & b",))
    assert "control character" in problems("Page", ("Sei\x07te",))
    assert "empty" in problems("Page", ("Seite", " "))
    assert "sentence end" in problems("Done.", ("Fertig",))


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
    for context, source, forms, kind in messages():
        if context == i18n.MESSAGES_CONTEXT and kind is None:
            assert all(len(text) <= len(source) + 4 for text in forms), source


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
    by_source = {source: forms[0] for _, source, forms, _ in messages()}
    assert by_source["Cancelling…"] == "Abbruch läuft …"
    assert "Neu prüfen" in by_source["Press Check again to look for the scanner."]
