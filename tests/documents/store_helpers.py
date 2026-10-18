"""A raw folder of pages (private, as the session makes it) and its draft, for the sidecar tests."""

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.draft_edit import move, rotate, set_included, toggle_split
from fastfoto_linux.documents.draft_store import REVIEW_FILE, THUMBS_DIR
from fastfoto_linux.session.raw import list_pages
from tests.doc_synth import Scene
from tests.documents.helpers import blank_scene, text_scene, write_scene

STAMP_DIR = ".raw/20261013T230000Z"
SCENES = (text_scene(1), blank_scene(2), text_scene(3), text_scene(4))


def raw_folder(tmp_path: Path, scenes: tuple[Scene, ...] = SCENES) -> tuple[Path, tuple[Path, ...]]:
    """``<tmp>/.raw/<stamp>/page-0001.png`` ... (mode 0700) and the pages ``list_pages`` finds."""
    folder = tmp_path / STAMP_DIR
    folder.mkdir(parents=True, mode=0o700)
    for number, scene in enumerate(scenes, start=1):
        write_scene(folder / f"page-{number:04d}.png", scene)
    return folder, list_pages(folder)


def store_settings(out: Path, **changes: Any) -> DocumentSettings:
    return replace(DocumentSettings(output_root=out, ocr=OcrMode.OFF, duplex=True), **changes)


def analysed(folder: Path, pages: tuple[Path, ...], settings: DocumentSettings) -> DocumentDraft:
    return analyse_document(pages, settings, thumbs=folder / THUMBS_DIR, encode=False)


def edited(draft: DocumentDraft) -> DocumentDraft:
    """Page 2 (looks blank) brought back, page 3 turned and removed, a split at 4, 4 moved up."""
    draft = set_included(draft, 2, True)
    draft = rotate(draft, 3, 1)
    draft = set_included(draft, 3, False)
    draft = toggle_split(draft, 4)
    return move(draft, 4, 0)


def sidecar(folder: Path) -> dict[str, Any]:
    return json.loads((folder / REVIEW_FILE).read_text(encoding="utf-8"))


def put_sidecar(folder: Path, data: Any) -> None:
    (folder / REVIEW_FILE).write_text(json.dumps(data), encoding="utf-8")


def touch_page(page: Path) -> None:
    info = page.stat()
    os.utime(page, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
