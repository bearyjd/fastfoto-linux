"""Immutable job contract for recoverable red-eye review (RED scaffold)."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Protocol

from fastfoto_linux.photo_edits import (
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
        raise NotImplementedError("photo edit jobs await the recorded RED baseline")
