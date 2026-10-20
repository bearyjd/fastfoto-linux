"""Synthetic photo review data; no image detector or scanner is used."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.photoeditjobs import PhotoEditResult, PhotoEditTools
from fastfoto_linux.gui.photoeditside import PhotoEditSide
from fastfoto_linux.gui.photos import PhotoItem
from fastfoto_linux.gui.state import State
from fastfoto_linux.photo_edits import EyeEdit, PhotoEditRecipe, PhotoPreview, PhotoSource
from tests.gui.helpers import FakeWorker


def source(folder: Path, *, dpi: int = 300) -> PhotoSource:
    path = folder / "synthetic.jpg"
    pixels = np.full((60, 100, 3), 100, dtype=np.uint8)
    Image.fromarray(pixels).save(path, dpi=(dpi, dpi))
    return PhotoSource(path, "a" * 64, path.stat().st_size, 100, 60, dpi, dpi, dpi, pixels)


def eyes() -> tuple[EyeEdit, ...]:
    return tuple(
        EyeEdit(name, "detected", (x, 20, x + 6, 26), (x + 3, 23), np.ones((6, 6), bool))
        for name, x in (("left", 20), ("right", 60))
    )


def preview(recipe: PhotoEditRecipe, generation: int, cache: Path) -> PhotoPreview:
    cache.mkdir(parents=True, exist_ok=True)
    for name in ("before", "after", "roi-before", "roi-after"):
        Image.new("RGB", (100, 60), (100, 100, 100)).save(cache / f"{name}-{generation}.png")
    return PhotoPreview(
        cache / f"before-{generation}.png",
        cache / f"after-{generation}.png",
        recipe.source.width,
        recipe.source.height,
        100,
        60,
        recipe.source.sha256,
        generation,
        cache / f"roi-before-{generation}.png",
        cache / f"roi-after-{generation}.png",
    )


class EditWorker(FakeWorker):
    busy = False

    def photo_edit_job(self, request):
        assert not self.busy, "editor must serialize through the existing worker"
        self.calls.append(("photo_edit", request))
        self.busy = True

    @property
    def requests(self):
        return [value for name, value in self.calls if name == "photo_edit"]


def setup(folder: Path):
    src = source(folder)
    worker = EditWorker()
    c = Controller(worker, ScanForm(output_folder=str(folder)))
    c._state = State.DONE
    c._photos = (PhotoItem(folder, 1, src.path, folder / "synthetic_a.jpg", None),)
    side = PhotoEditSide(c, cache_dir=folder / "editor-cache")
    c.photo_edit = side
    return SimpleNamespace(source=src, worker=worker, controller=c, side=side)


def opened(folder: Path):
    page = setup(folder)
    page.side.open_photo(0)
    request = page.worker.requests[-1]
    recipe = PhotoEditRecipe(page.source, eyes())
    finish(
        page,
        PhotoEditResult(
            "open", request.generation, recipe, preview(recipe, request.generation, folder)
        ),
    )
    return page


def finish(page, result: PhotoEditResult):
    page.worker.busy = False
    page.side.complete(result)


def fake_tools(src: PhotoSource, calls: list):
    recipe = PhotoEditRecipe(src, eyes())

    def record(name, answer):
        def call(*args, **kwargs):
            calls.append((name, args, kwargs))
            return answer

        return call

    return replace(
        PhotoEditTools(),
        load=record("load", src),
        detect=record("detect", recipe.eyes),
        reopen=record("reopen", (src, recipe)),
        preview=lambda s, r, **kw: preview(r, kw["generation"], kw["cache_dir"]),
    )
