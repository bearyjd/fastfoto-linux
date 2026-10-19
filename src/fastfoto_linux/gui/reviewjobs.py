"""Folder analysis, PDF writing and bounded previews on the existing worker thread."""

import functools
import io
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from fastfoto_linux.documents import DocumentCancelledError, DocumentError, DocumentSettings
from fastfoto_linux.documents.auto_colour import page_colour
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.draft_store import THUMBS_DIR, open_draft
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy
from fastfoto_linux.documents.private_io import ensure_private_dir, write_private_atomic
from fastfoto_linux.documents.write import write_document
from fastfoto_linux.gui.docreport import os_error_words
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult, Stage
from fastfoto_linux.session.raw import list_pages

if TYPE_CHECKING:
    from fastfoto_linux.gui.doctools import DocumentTools
    from fastfoto_linux.gui.worker import WorkerSink

logger = logging.getLogger(__name__)
PREVIEW_DIR = "previews"
PREVIEW_MAX_PX = 1600
PREVIEW_QUALITY = 90
Job = Callable[[threading.Event], Callable[[], None]]


@dataclass(frozen=True)
class PreviewRequest:
    """The immutable page, request policy and view captured before worker dispatch."""

    draft: DocumentDraft
    number: int
    policy: ColourPolicy | ColourMode = ColourPolicy.COLOUR
    view: str = "source"

    def __post_init__(self) -> None:
        ColourPolicy(self.policy)
        if self.view not in {"source", "output"}:
            raise ValueError("choose a source or output preview")


@dataclass(frozen=True)
class PreviewCompletion:
    request: PreviewRequest
    path: Path | None
    error: str = ""


PreviewResult = tuple[DocumentDraft, int, Path | None, str] | PreviewCompletion


def output_preview_names(number: int) -> tuple[str, ...]:
    """Only these bounded generated variants may be accepted or removed with originals."""
    return tuple(
        f"page-{number:04d}-output-{mode.value}{suffix}.jpg"
        for mode in ColourMode
        for suffix in ("", "-r0", "-r1", "-r2", "-r3")
    )


def _preview_image(request: PreviewRequest, cancel: threading.Event) -> tuple[Image.Image, str]:
    draft, number = request.draft, request.number
    page = draft.pages[number - 1]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    if request.view == "source":
        return Image.fromarray(loaded.pixels), ""
    mode = page_colour(draft, page, request.policy)
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    turns = draft.edits.get(number, PageEdit()).quarter_turns
    if turns:
        loaded = replace(loaded, pixels=np.rot90(loaded.pixels, -turns).copy())
    return Image.fromarray(render_page(loaded, mode)), f"-output-{mode.value}-r{turns}"


def make_preview(
    draft: DocumentDraft,
    number: int,
    cancel: threading.Event,
    *,
    policy: ColourPolicy | ColourMode = ColourPolicy.COLOUR,
    view: str = "source",
) -> Path:
    """Trim raw pixels, optionally render full output, then write a bounded private preview."""
    request = PreviewRequest(draft, number, policy, view)
    if draft.raw_dir is None or not 1 <= number <= len(draft.pages):
        raise ValueError("the preview needs a page in its original folder")
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    image, suffix = _preview_image(request, cancel)
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    image.thumbnail((PREVIEW_MAX_PX, PREVIEW_MAX_PX))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=PREVIEW_QUALITY)
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    folder = draft.raw_dir / PREVIEW_DIR
    ensure_private_dir(folder)
    path = folder / f"page-{number:04d}{suffix}.jpg"
    write_private_atomic(path, buffer.getvalue())
    return path


def _result(draft: DocumentDraft) -> DocumentSessionResult:
    folder = draft.raw_dir
    return DocumentSessionResult(
        pages_scanned=len(draft.pages),
        raw_dir=folder,
        raw_reason=DocumentRawReason.REVIEW,
        kept_pages=tuple(folder / page.name for page in draft.pages) if folder else (),
        draft=draft,
    )


class ReviewJobs:
    def __init__(
        self, sink: "WorkerSink", start: Callable[[Job], None], tools: "DocumentTools"
    ) -> None:
        self._sink, self._start = sink, start
        self._open = tools.open_review or open_draft
        self._write = tools.write_review or write_document
        self._preview = tools.preview_review or make_preview

    def analyse_folder(self, folder: Path, settings: DocumentSettings) -> None:
        self._start(lambda cancel: self._analyse(folder, settings, cancel))

    def _analyse(
        self, folder: Path, settings: DocumentSettings, cancel: threading.Event
    ) -> Callable[[], None]:
        self._sink.on_stage(Stage.PROCESSING)
        try:
            draft = self._open(
                folder,
                list_pages(folder),
                settings,
                thumbs=folder / THUMBS_DIR,
                cancel=cancel,
                on_page=lambda n, total: self._sink.on_build_page((n, total)),
            )
        except DocumentCancelledError:
            result = DocumentSessionResult(cancelled=True, raw_dir=folder)
        except (DocumentError, OSError) as error:
            result = DocumentSessionResult(error=error, raw_dir=folder)
        else:
            result = _result(draft)
        return functools.partial(self._sink.on_finished, result)

    def write_draft(self, draft: DocumentDraft, settings: DocumentSettings) -> None:
        self._start(lambda cancel: self._written(draft, settings, cancel))

    def _written(
        self, draft: DocumentDraft, settings: DocumentSettings, cancel: threading.Event
    ) -> Callable[[], None]:
        result = _result(draft)
        try:
            document = self._write(
                draft,
                settings,
                cancel=cancel,
                on_page=lambda n, total: self._sink.on_build_page((n, total)),
                on_ocr=self._sink.on_ocr,
            )
        except DocumentCancelledError:
            result = replace(result, cancelled=True)
        except DocumentError as error:
            result = replace(result, error=error)
        except OSError as error:
            logger.warning("the reviewed PDF could not be saved: %s", error)
            result = replace(result, error=OSError(error.errno, os_error_words(error)))
        else:
            result = replace(result, document=document)
        return functools.partial(self._sink.on_finished, result)

    def preview_page(
        self, draft: DocumentDraft | PreviewRequest, number: int | None = None
    ) -> None:
        if isinstance(draft, PreviewRequest):
            self._start(lambda cancel: self._snapshot_previewed(draft, cancel))
            return
        assert number is not None
        self._start(lambda cancel: self._previewed(draft, number, cancel))

    def _previewed(
        self, draft: DocumentDraft, number: int, cancel: threading.Event
    ) -> Callable[[], None]:
        try:
            answer = (draft, number, self._preview(draft, number, cancel), "")
        except (DocumentError, OSError, ValueError) as error:
            answer = (draft, number, None, str(error))
        return functools.partial(self._sink.on_review_preview, answer)

    def _snapshot_previewed(
        self, request: PreviewRequest, cancel: threading.Event
    ) -> Callable[[], None]:
        try:
            path = self._preview(
                request.draft, request.number, cancel, policy=request.policy, view=request.view
            )
            answer = PreviewCompletion(request, path)
        except (DocumentError, OSError, ValueError) as error:
            answer = PreviewCompletion(request, None, str(error))
        return functools.partial(self._sink.on_review_preview, answer)
