"""Discover installed OCR languages and prepare verified offline model overlays."""

import threading
from dataclasses import dataclass
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("ocr_language_catalog.json")


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    size: int
    installed: bool = False
    downloaded: bool = False


@dataclass(frozen=True)
class Inventory:
    languages: tuple[Language, ...]
    error: str = ""
    orientation: Language | None = None

    @property
    def installed(self) -> tuple[Language, ...]:
        return tuple(language for language in self.languages if language.installed)

    @property
    def available(self) -> tuple[Language, ...]:
        return tuple(language for language in self.languages if not language.installed)


def discover_languages(*, cancel: threading.Event | None = None) -> Inventory:
    raise NotImplementedError


def require_languages(langs: str) -> None:
    raise NotImplementedError


def prepare_tessdata(langs: str, folder: Path, env: dict[str, str]) -> dict[str, str]:
    raise NotImplementedError
