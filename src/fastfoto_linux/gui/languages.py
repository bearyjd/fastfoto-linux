"""Language picker presentation, preserving the document form's ordered OCR codes."""

from typing import Any

from fastfoto_linux.documents.ocr_languages import Inventory, Language

KIBIBYTE = 1024
MEBIBYTE = KIBIBYTE * KIBIBYTE


def format_bytes(size: int) -> str:
    if size < KIBIBYTE:
        return f"{size:,} B"
    if size < MEBIBYTE:
        return f"{size / KIBIBYTE:.1f} KiB"
    return f"{size / MEBIBYTE:.1f} MiB"


def selected_codes(langs: str) -> tuple[str, ...]:
    return tuple(code for code in langs.split("+") if code)


def toggle_language(langs: str, code: str, checked: bool) -> str:
    codes = selected_codes(langs)
    if checked:
        return langs if code in codes else "+".join((*codes, code))
    return "+".join(item for item in codes if item != code)


def language_rows(inventory: Inventory, langs: str, search: str = "") -> list[dict[str, Any]]:
    selected = selected_codes(langs)
    known = {language.code for language in inventory.languages}
    extra = tuple(Language(code, code, 0) for code in selected if code not in known)
    needle = search.strip().casefold()
    return [
        {
            "code": language.code,
            "name": language.name,
            "selected": language.code in selected,
            "installed": language.installed,
            "status": _status(language),
        }
        for language in (*inventory.languages, *extra)
        if not needle or needle in f"{language.name} {language.code}".casefold()
    ]


def _status(language: Language) -> str:
    if language.installed:
        return "Installed"
    if language.size:
        return f"Download required · {format_bytes(language.size)}"
    return "Unavailable · install this custom language locally"


def language_summary(inventory: Inventory, langs: str) -> str:
    if not selected_codes(langs):
        return "Choose at least one text language."
    names = {language.code: language.name for language in inventory.languages}
    return "Selected: " + ", ".join(
        f"{names.get(code, code)} ({code})" for code in selected_codes(langs)
    )


def missing_languages(inventory: Inventory, langs: str) -> tuple[str, ...]:
    installed = {language.code for language in inventory.installed}
    missing = tuple(code for code in selected_codes(langs) if code not in installed)
    if langs and inventory.orientation is not None and not inventory.orientation.installed:
        return (*missing, inventory.orientation.code)
    return missing


def download_codes(inventory: Inventory, langs: str) -> tuple[str, ...]:
    if not selected_codes(langs):
        return ()
    available = {language.code for language in inventory.languages if language.size > 0}
    if inventory.orientation is not None:
        available.add(inventory.orientation.code)
    return tuple(code for code in missing_languages(inventory, langs) if code in available)
