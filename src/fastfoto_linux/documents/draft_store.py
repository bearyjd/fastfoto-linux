"""STUB (red)."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.documents.analyse import ANALYSIS_VERSION  # noqa: F401
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.ocr import OcrMode
from fastfoto_linux.documents.settings import DocumentSettings

REVIEW_FILE = "review.json"
THUMBS_DIR = "thumbs"
MAX_REVIEW_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class StoredOptions:
    name: str
    colour: ColourMode
    ocr: OcrMode
    langs: str


@dataclass(frozen=True)
class StoredReview:
    draft: DocumentDraft
    analysis_version: int
    options: StoredOptions | None


def save_draft(draft: DocumentDraft, settings: DocumentSettings | None = None) -> None:
    raise NotImplementedError


def read_review(folder: Path, pages: Sequence[Path]) -> StoredReview | None:
    raise NotImplementedError


def load_draft(
    folder: Path, pages: Sequence[Path], settings: DocumentSettings | None = None
) -> DocumentDraft | None:
    raise NotImplementedError


def open_draft(
    folder: Path,
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    fresh: bool = False,
    thumbs: Path | None = None,
) -> DocumentDraft:
    raise NotImplementedError
