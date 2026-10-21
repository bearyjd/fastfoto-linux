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
from fastfoto_linux.documents.cleanup import page_cleanup
from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.draft_store import THUMBS_DIR, open_draft
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy
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
PREVIEW_CROP_PX = 1024  # the actual-pixel crop: a window of the output, never scaled
CROP_SCALE = 1000  # the crop centre is given in permille of the page
Job = Callable[[threading.Event], Callable[[], None]]


@dataclass(frozen=True)
class PreviewRequest:
    """The immutable page, request policy and view captured before worker dispatch."""

    draft: DocumentDraft
    number: int
    policy: ColourPolicy | ColourMode = ColourPolicy.COLOUR
    view: str = "source"
    cleaned: bool = True
    crop: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        ColourPolicy(self.policy)
        if self.view not in {"source", "output"}:
            raise ValueError("choose a source or output preview")
        if self.crop is not None and not _valid_crop(self.crop):
            raise ValueError("the crop centre is two whole numbers from 0 to 1000")


def _valid_crop(crop: object) -> bool:
    try:
        x, y = crop  # type: ignore[misc]
    except (TypeError, ValueError):
        return False
    return isinstance(crop, tuple) and all(type(v) is int and 0 <= v <= CROP_SCALE for v in (x, y))


@dataclass(frozen=True)
class PreviewCompletion:
    request: PreviewRequest
    path: Path | None
    error: str = ""


PreviewResult = tuple[DocumentDraft, int, Path | None, str] | PreviewCompletion


def output_preview_names(number: int) -> tuple[str, ...]:
    """Only these bounded generated variants may be accepted or removed with originals.

    The legacy names (made before paper cleanup existed) stay, so old previews are still removed.
    """
    legacy = tuple(
        f"page-{number:04d}-output-{mode.value}{suffix}.jpg"
        for mode in ColourMode
        for suffix in ("", "-r0", "-r1", "-r2", "-r3")
    )
    current = tuple(
        f"page-{number:04d}{_output_suffix(mode, level, turns)}{extension}"
        for mode in ColourMode
        for level in CleanupPolicy
        for turns in range(4)
        for extension in (".jpg", "-crop.png")
    )
    return legacy + current


def _output_suffix(mode: ColourMode, cleanup: CleanupPolicy, turns: int) -> str:
    return f"-output-{mode.value}-{cleanup.value}-r{turns}"


def _preview_image(request: PreviewRequest, cancel: threading.Event) -> tuple[np.ndarray, str]:
    """The pixels to show and the file-name suffix that tells which variant they are."""
    draft, number = request.draft, request.number
    page = draft.pages[number - 1]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    if request.view == "source":
        return loaded.pixels, ""
    mode = page_colour(draft, page, request.policy)
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    turns = draft.edits.get(number, PageEdit()).quarter_turns
    if turns:
        loaded = replace(loaded, pixels=np.rot90(loaded.pixels, -turns).copy())
    cleanup = page_cleanup(draft, page) if request.cleaned else CleanupPolicy.OFF
    if cleanup is CleanupPolicy.OFF:
        # Same pixels as render_page(loaded, mode, OFF, cancel=cancel); kept as the short call
        # because tests that monkeypatch render_page expect it without the cleanup arguments.
        pixels = render_page(loaded, mode)
    else:
        pixels = render_page(loaded, mode, cleanup, cancel=cancel)
    return pixels, _output_suffix(mode, cleanup, turns)


def _crop_window(pixels: np.ndarray, centre: tuple[int, int]) -> np.ndarray:
    """The ``PREVIEW_CROP_PX`` square (or the whole page if smaller) around a permille centre."""
    height, width = pixels.shape[:2]
    window_w, window_h = min(PREVIEW_CROP_PX, width), min(PREVIEW_CROP_PX, height)
    left = min(max(0, centre[0] * width // CROP_SCALE - window_w // 2), width - window_w)
    top = min(max(0, centre[1] * height // CROP_SCALE - window_h // 2), height - window_h)
    return pixels[top : top + window_h, left : left + window_w]


def _encode_preview(pixels: np.ndarray, crop: tuple[int, int] | None) -> tuple[bytes, str]:
    """A bounded JPEG of the page, or a lossless PNG of the actual pixels around ``crop``."""
    buffer = io.BytesIO()
    if crop is not None:
        Image.fromarray(np.ascontiguousarray(_crop_window(pixels, crop))).save(buffer, "PNG")
        return buffer.getvalue(), "-crop.png"
    image = Image.fromarray(pixels)
    image.thumbnail((PREVIEW_MAX_PX, PREVIEW_MAX_PX))
    image.save(buffer, "JPEG", quality=PREVIEW_QUALITY)
    return buffer.getvalue(), ".jpg"


def make_preview(  # noqa: PLR0913 - the request's own fields, passed through
    draft: DocumentDraft,
    number: int,
    cancel: threading.Event,
    *,
    policy: ColourPolicy | ColourMode = ColourPolicy.COLOUR,
    view: str = "source",
    cleaned: bool = True,
    crop: tuple[int, int] | None = None,
) -> Path:
    """Trim raw pixels, optionally render full output, then write a bounded private preview."""
    request = PreviewRequest(draft, number, policy, view, cleaned, crop)
    if draft.raw_dir is None or not 1 <= number <= len(draft.pages):
        raise ValueError("the preview needs a page in its original folder")
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    pixels, suffix = _preview_image(request, cancel)
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    data, extension = _encode_preview(pixels, crop if view == "output" else None)
    if cancel.is_set():
        raise DocumentCancelledError("preview cancelled")
    folder = draft.raw_dir / PREVIEW_DIR
    ensure_private_dir(folder)
    path = folder / f"page-{number:04d}{suffix}{extension}"
    write_private_atomic(path, data)
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
                request.draft,
                request.number,
                cancel,
                policy=request.policy,
                view=request.view,
                cleaned=request.cleaned,
                crop=request.crop,
            )
            answer = PreviewCompletion(request, path)
        except (DocumentError, OSError, ValueError) as error:
            answer = PreviewCompletion(request, None, str(error))
        return functools.partial(self._sink.on_review_preview, answer)
