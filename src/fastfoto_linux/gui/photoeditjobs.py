"""Immutable job contract for recoverable red-eye review ."""

import functools
import os
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Any, Protocol

from fastfoto_linux.photo_edits import (
    PhotoEditCancelledError,
    PhotoEditRecipe,
    PhotoPreview,
    SavedPhotoEdit,
    detect_eyes,
    load_source,
    make_preview,
    manual_eye,
    open_edit,
    save_edit,
)

Job = Callable[[Event], Callable[[], None]]


@dataclass(frozen=True)
class PhotoEditRequest:
    operation: str
    generation: int
    path: Path | None = None
    recipe: PhotoEditRecipe | None = None
    selected_id: str | None = None


@dataclass(frozen=True)
class PhotoEditResult:
    operation: str
    generation: int
    recipe: PhotoEditRecipe | None = None
    preview: PhotoPreview | None = None
    saved: SavedPhotoEdit | None = None
    error: str = ""
    cancelled: bool = False


@dataclass(frozen=True)
class PhotoEditTools:
    load: Callable[..., Any] = load_source
    detect: Callable[..., Any] = detect_eyes
    manual: Callable[..., Any] = manual_eye
    preview: Callable[..., Any] = make_preview
    save: Callable[..., Any] = save_edit
    reopen: Callable[..., Any] = open_edit


class PhotoEditSink(Protocol):
    def on_photo_edit_result(self, result: PhotoEditResult) -> None: ...


class PhotoEditJobs:
    def __init__(
        self,
        sink: PhotoEditSink,
        start: Callable[[Job], None],
        tools: PhotoEditTools,
        cache_dir: Path,
    ) -> None:
        self._sink, self._start = sink, start
        self._tools, self._cache_dir = tools, cache_dir
        self._cache_paths: set[Path] = set()
        self._cache_lock = Lock()
        self._closed = False

    def submit(self, request: PhotoEditRequest) -> None:
        self._start(lambda cancel: self._run(request, cancel))

    def _run(self, request: PhotoEditRequest, cancel: Event) -> Callable[[], None]:
        try:
            result = self._perform(request, cancel)
        except PhotoEditCancelledError:
            result = PhotoEditResult(request.operation, request.generation, cancelled=True)
        except Exception as error:
            result = PhotoEditResult(request.operation, request.generation, error=str(error))
        return functools.partial(self._sink.on_photo_edit_result, result)

    def _perform(self, request: PhotoEditRequest, cancel: Event) -> PhotoEditResult:
        _check_cancel(cancel)
        recipe = self._recipe(request, cancel)
        _check_cancel(cancel)
        if request.operation == "save":
            saved = self._tools.save(recipe.source, recipe, cancel=cancel)
            return PhotoEditResult("save", request.generation, recipe=recipe, saved=saved)
        selected = request.selected_id
        if selected is None and request.operation in {"open", "reopen"} and recipe.eyes:
            selected = recipe.eyes[0].id
        preview = self._tools.preview(
            recipe.source,
            recipe,
            cache_dir=self._cache_dir,
            generation=request.generation,
            cancel=cancel,
            selected_id=selected,
        )
        self._track_preview(preview)
        return PhotoEditResult(request.operation, request.generation, recipe, preview)

    def _recipe(self, request: PhotoEditRequest, cancel: Event) -> PhotoEditRecipe:
        if request.operation in {"open", "reopen"}:
            if request.path is None:
                raise ValueError("choose an original JPEG or saved edit sidecar")
            if request.operation == "reopen":
                _source, recipe = self._tools.reopen(request.path)
                return recipe
            source = self._tools.load(request.path)
            _check_cancel(cancel)
            return PhotoEditRecipe(source, self._tools.detect(source, cancel=cancel))
        if request.operation not in {"preview", "save"} or request.recipe is None:
            raise ValueError("photo edit job needs a supported operation and draft")
        return request.recipe

    def _track_preview(self, preview: PhotoPreview) -> None:
        paths = {
            p
            for p in (preview.before, preview.after, preview.roi_before, preview.roi_after)
            if p is not None and p.parent == self._cache_dir
        }
        with self._cache_lock:
            self._cache_paths = paths | {p for p in self._cache_paths if p.exists()}
            if self._closed:
                self._remove_cached_paths()
                raise PhotoEditCancelledError("photo review window closed")

    def close(self) -> None:
        """Clean this worker's returned cache files, including a job ending after shutdown."""
        with self._cache_lock:
            self._closed = True
            self._remove_cached_paths()

    def _remove_cached_paths(self) -> None:
        for path in self._cache_paths:
            with suppress(OSError):
                path.unlink()
        self._cache_paths.clear()
        with suppress(OSError):
            self._cache_dir.rmdir()


def _check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise PhotoEditCancelledError("photo review cancelled")


def new_cache_dir() -> Path:
    """Choose one editor's private cache namespace without touching the filesystem."""
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "fastfoto-linux" / "photo-edits" / uuid.uuid4().hex
