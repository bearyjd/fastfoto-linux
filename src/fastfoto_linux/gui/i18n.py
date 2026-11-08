"""The interface languages: which exist, how a message is marked for translation, where they live.

Plain Python (no Qt), so that the modules which write the messages stay importable everywhere.
The translation itself happens in ``gui.qt.translation``.

The interface language is not the OCR language: ``deu`` for text recognition is a different
setting (``DocumentForm.langs``) and has nothing to do with this one.
"""

from dataclasses import dataclass
from pathlib import Path

DEFAULT_LANGUAGE = "en"
MESSAGES_CONTEXT = "messages"  # the context of every message marked in Python
CATALOG_PREFIX = "fastfoto_"


@dataclass(frozen=True)
class UiLanguage:
    """One interface language; ``partial`` when part of the text stays English."""

    code: str
    label: str
    partial: bool


# The labels are not translated: each one is written in its own language, so that it can be read
# whichever language is active. German is a pilot and says so in its label.
UI_LANGUAGES = (
    UiLanguage("en", "English", partial=False),
    UiLanguage("de", "Deutsch (partial)", partial=True),
)
_CODES = tuple(language.code for language in UI_LANGUAGES)


def QT_TRANSLATE_NOOP(context: str, text: str) -> str:
    """Mark ``text`` for translation and return it unchanged.

    ``lupdate`` finds the call by name. The translation is looked up where the text reaches the
    window (``gui.qt.translation.translate_message``), so without a translator nothing changes.
    """
    return text


def ui_language_code(value: object) -> str:
    """``value`` when it is the code of an interface language, else English."""
    return value if isinstance(value, str) and value in _CODES else DEFAULT_LANGUAGE


def catalog_dir() -> Path:
    """The folder of the translation files shipped with the package; the only one ever read."""
    return Path(__file__).resolve().parent / "translations"


def catalog_path(code: object) -> Path | None:
    """The compiled catalog of a language other than English, None when there is no such code."""
    if not isinstance(code, str) or code == DEFAULT_LANGUAGE or ui_language_code(code) != code:
        return None
    return catalog_dir() / f"{CATALOG_PREFIX}{code}.qm"


def source_path(code: str) -> Path:
    """The ``.ts`` file the catalog of ``code`` is compiled from (translators edit this one)."""
    return catalog_dir() / f"{CATALOG_PREFIX}{ui_language_code(code)}.ts"


def pin_path(code: str) -> Path:
    """The file pinning the SHA-256 of the compiled catalog (written by ``i18n.sh release``)."""
    return catalog_dir() / f"{CATALOG_PREFIX}{ui_language_code(code)}.qm.sha256"
