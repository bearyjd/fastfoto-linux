"""Editor backend work is injected and completed through the shared worker lane."""

from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from fastfoto_linux.gui.photoeditjobs import PhotoEditJobs, PhotoEditRequest
from fastfoto_linux.photo_edits import PhotoEditCancelledError, PhotoEditRecipe, SavedPhotoEdit
from tests.gui.photoedit_helpers import eyes, fake_tools, source


def queued(out, *, tools=None):
    src = source(out)
    calls, jobs, results = [], [], []
    injected = tools or fake_tools(src, calls)
    sink = SimpleNamespace(on_photo_edit_result=results.append)
    runner = PhotoEditJobs(sink, jobs.append, injected, out / "private-preview")
    return SimpleNamespace(source=src, calls=calls, jobs=jobs, results=results, runner=runner)


def execute(p, request, *, cancel=None):
    p.runner.submit(request)
    assert len(p.jobs) == 1
    assert p.results == []
    report = p.jobs[0](cancel or Event())
    assert p.results == []  # Worker clears busy before invoking the result callback.
    report()
    assert len(p.results) == 1
    return p.results[0]


def test_open_loads_original_detects_then_returns_generation_and_bounded_preview(out):
    p = queued(out)
    result = execute(p, PhotoEditRequest("open", 7, path=p.source.path))
    assert [name for name, _, _ in p.calls] == ["load", "detect"]
    assert p.calls[0][1] == (p.source.path,)
    assert result.operation == "open" and result.generation == 7
    assert result.recipe.source is p.source
    assert len(result.recipe.eyes) == 2
    assert not any(eye.accepted for eye in result.recipe.eyes)
    assert result.preview.generation == 7
    assert result.preview.after.parent == out / "private-preview"


def test_reopen_never_calls_detector_or_loads_enhanced_pixels(out):
    p = queued(out)
    path = out / "synthetic_edit-0001.json"
    result = execute(p, PhotoEditRequest("reopen", 11, path=path))
    assert [name for name, _, _ in p.calls] == ["reopen"]
    assert p.calls[0][1] == (path,)
    assert result.recipe.source.path == p.source.path
    assert not result.error


def test_preview_passes_full_recipe_selected_eye_and_cancel_event(out):
    src = source(out)
    calls = []
    recipe = PhotoEditRecipe(src, eyes())
    tools = fake_tools(src, calls)
    original_preview = tools.preview

    def spy(*args, **kwargs):
        calls.append(("preview", args, kwargs))
        return original_preview(*args, **kwargs)

    p = queued(out, tools=replace(tools, preview=spy))
    cancel = Event()
    result = execute(
        p, PhotoEditRequest("preview", 23, recipe=recipe, selected_id="right"), cancel=cancel
    )
    assert calls[0][1] == (src, recipe)
    assert calls[0][2]["cancel"] is cancel
    assert calls[0][2]["selected_id"] == "right"
    assert result.preview.source_sha256 == src.sha256


def test_save_uses_original_recipe_and_only_reports_complete_publication(out):
    src = source(out)
    recipe = PhotoEditRecipe(src, eyes())
    saved = SavedPhotoEdit(
        out / "synthetic_edit-0001.jpg", out / "synthetic_edit-0001.json", recipe
    )
    calls = []

    def save(s, r, **kwargs):
        calls.append((s, r, kwargs))
        return saved

    p = queued(out, tools=replace(fake_tools(src, []), save=save))
    result = execute(p, PhotoEditRequest("save", 5, recipe=recipe))
    assert calls[0][:2] == (src, recipe)
    assert result.saved is saved
    assert result.recipe is recipe
    assert result.preview is None


@pytest.mark.parametrize("error", [ValueError("source hash changed"), OSError("disk full")])
def test_errors_are_results_with_original_generation_and_no_partial_save(out, error):
    src = source(out)

    def fail(*args, **kwargs):
        raise error

    p = queued(out, tools=replace(fake_tools(src, []), save=fail))
    result = execute(p, PhotoEditRequest("save", 31, recipe=PhotoEditRecipe(src)))
    assert result.generation == 31
    assert result.error == str(error)
    assert result.saved is None
    assert not result.cancelled


def test_cancelled_backend_is_reported_without_a_save_or_unexpected_error(out):
    src = source(out)

    def cancel(*args, **kwargs):
        raise PhotoEditCancelledError("cancelled")

    p = queued(out, tools=replace(fake_tools(src, []), save=cancel))
    result = execute(p, PhotoEditRequest("save", 41, recipe=PhotoEditRecipe(src)))
    assert result.cancelled
    assert result.saved is None
    assert not result.error


def test_pre_cancelled_open_never_decodes_or_detects(out):
    p = queued(out)
    cancel = Event()
    cancel.set()
    result = execute(p, PhotoEditRequest("open", 52, path=p.source.path), cancel=cancel)
    assert result.cancelled
    assert p.calls == []
