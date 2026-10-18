"""Language picker presentation, preserving the document form's ordered OCR codes."""

from typing import Any

from fastfoto_linux.documents.ocr_languages import Inventory


def toggle_language(langs: str, code: str, checked: bool) -> str:
    raise NotImplementedError


def language_rows(inventory: Inventory, langs: str, search: str = "") -> list[dict[str, Any]]:
    raise NotImplementedError


def language_summary(inventory: Inventory, langs: str) -> str:
    raise NotImplementedError


def missing_languages(inventory: Inventory, langs: str) -> tuple[str, ...]:
    raise NotImplementedError


def download_codes(inventory: Inventory, langs: str) -> tuple[str, ...]:
    raise NotImplementedError
