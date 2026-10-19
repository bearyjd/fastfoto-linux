"""Immutable job contract for recoverable red-eye review ."""

import functools
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
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


def _check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise PhotoEditCancelledError("photo review cancelled")


def new_cache_dir() -> Path:
    """Choose one editor's private cache namespace without touching the filesystem."""
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "fastfoto-linux" / "photo-edits" / uuid.uuid4().hex
