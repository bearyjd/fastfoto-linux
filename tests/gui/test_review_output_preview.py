"""Output previews use the full-resolution renderer and immutable worker request identity."""

import stat
import threading
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents import ColourMode, ColourPolicy, DocumentCancelledError
from fastfoto_linux.documents.draft import TrimBox
from fastfoto_linux.gui import reviewjobs, reviewside
from fastfoto_linux.gui.review import ReviewState
from fastfoto_linux.gui.reviewjobs import (
    PREVIEW_MAX_PX,
    PreviewCompletion,
    PreviewRequest,
    ReviewJobs,
    make_preview,
)
from tests.gui.doc_helpers import DocRecordingSink, clean_document
from tests.gui.test_review_colour import decided_draft
from tests.gui.test_reviewside import opened


def test_output_renders_trimmed_full_resolution_before_bounding_and_keeps_raw(out, monkeypatch):
    source = decided_draft(out)
    page = replace(source.pages[0], trim=TrimBox(0, 0, 0, 0, False))
    source = replace(source, pages=(page,))
    raw = out / page.name
    Image.new("RGB", (1800, 2400), "white").save(raw, dpi=(300, 300))
    original = raw.read_bytes()
    calls = []

    def rendered(loaded, mode):
        calls.append((loaded.pixels.shape, mode))
        return np.zeros(loaded.pixels.shape[:2], dtype=np.uint8)

    monkeypatch.setattr(reviewjobs, "render_page", rendered, raising=False)
    output = make_preview(source, 1, threading.Event(), policy=ColourPolicy.AUTO, view="output")
    coarse = make_preview(source, 1, threading.Event())
    assert calls == [((2400, 1800, 3), ColourMode.GREY)]
    assert output != coarse
    with Image.open(output) as image:
        assert max(image.size) == PREVIEW_MAX_PX
        assert image.convert("L").getextrema() == (0, 0)
    with Image.open(coarse) as image:
        assert image.convert("L").getextrema() == (255, 255)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert raw.read_bytes() == original


def test_cancelled_output_preview_publishes_nothing(out):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DocumentCancelledError):
        make_preview(decided_draft(out), 1, cancel, policy=ColourPolicy.AUTO, view="output")
    assert not (out / "previews").exists()


def test_worker_completion_carries_the_exact_frozen_policy_and_view_snapshot(out):
    request = PreviewRequest(decided_draft(out), 1, ColourPolicy.AUTO, "output")
    with pytest.raises(FrozenInstanceError):
        request.view = "source"
    tasks, seen = [], []
    sink = DocRecordingSink()
    sink.on_review_preview = seen.append
    tools = SimpleNamespace(open_review=None, write_review=None, preview_review=None)
    worker = ReviewJobs(sink, tasks.append, tools)
    worker._preview = lambda *args, **kwargs: out / "previews" / "page-0001-output-grey.jpg"
    worker.preview_page(request)
    tasks[0](threading.Event())()
    assert isinstance(seen[0], PreviewCompletion)
    assert seen[0].request is request
    assert seen[0].error == ""


def test_policy_change_rejects_old_completion_even_for_the_same_draft_and_page(out):
    side, page = opened(out)
    calls = []
    page.worker.preview_page = lambda *args: calls.append(args)
    side._settings = replace(side._settings, colour=ColourPolicy.AUTO)
    side.preview(1, "output")
    old = calls[-1][0]
    side._settings = replace(side._settings, colour=ColourPolicy.GREY)
    side.preview(1, "output")
    latest = calls[-1][0]
    assert old.draft is latest.draft
    assert (old.policy, latest.policy) == (ColourPolicy.AUTO, ColourPolicy.GREY)
    side.preview_ready(PreviewCompletion(old, out / "previews" / "page-0001-output-grey.jpg"))
    assert side.preview_path is None
    side.preview_ready(PreviewCompletion(latest, out / "previews" / "page-0001-output-grey.jpg"))
    assert side.preview_number == 1


def test_override_and_view_change_invalidate_ready_output_and_inflight_completion(out):
    side, page = opened(out)
    calls = []
    page.worker.preview_page = lambda *args: calls.append(args)
    side.preview(1, "output")
    old = calls[-1][0]
    output = out / "previews" / "page-0001-output-colour.jpg"
    side.preview_ready(PreviewCompletion(old, output))
    assert side.preview_path == output
    side.edit("set_colour", 1, ColourPolicy.BW)
    assert side.preview_path is None
    side.preview(1, "output")
    inflight = calls[-1][0]
    side.preview(1, "source")
    side.preview_ready(PreviewCompletion(inflight, output))
    assert side.preview_path is None
    side.preview_ready(PreviewCompletion(old, output))
    assert side.preview_path is None


def test_busy_preview_coalesces_to_the_newest_snapshot_and_ignores_same_key_old_generation(out):
    side, page = opened(out)
    calls = []
    page.worker.preview_page = lambda *args: calls.append(args)
    side.preview(1, "output")
    old = calls[-1][0]
    page.worker.busy = True
    side.preview(2, "output")
    side.preview(1, "source")
    side.preview(1, "output")
    latest = side._preview_requested
    assert latest is not old
    assert len(calls) == 1
    page.worker.busy = False
    path = out / "previews" / "page-0001-output-colour-r0.jpg"
    side.preview_ready(PreviewCompletion(old, path))
    assert side.preview_path is None
    assert len(calls) == 2
    assert calls[-1] == (latest,)
    side.preview_ready(PreviewCompletion(old, path))
    assert side.preview_path is None
    side.preview_ready(PreviewCompletion(latest, path))
    assert side.preview_path == path


def test_busy_source_completion_dispatches_current_output_without_relabelling_source(out):
    side, page = opened(out)
    calls = []
    page.worker.preview_page = lambda *args: calls.append(args)
    source = side.state.draft
    side.preview(1)
    page.worker.busy = True
    side.preview(1, "output")
    page.worker.busy = False
    side.preview_ready((source, 1, out / "previews" / "page-0001.jpg", ""))
    assert side.preview_path is None
    assert side.preview_view == "output"
    assert calls[-1][0] is side._preview_requested
    assert calls[-1][0].view == "output"


def test_output_rotation_happens_before_rendering_once(out, monkeypatch):
    source = decided_draft(out)
    page = replace(source.pages[0], trim=TrimBox(0, 0, 0, 0, False))
    source = replace(source, pages=(page,))
    source = ReviewState(source).rotate(1, 1).draft
    raw = out / page.name
    Image.new("RGB", (160, 240), "white").save(raw, dpi=(300, 300))
    original = raw.read_bytes()
    shapes = []

    def rendered(loaded, mode):
        shapes.append(loaded.pixels.shape)
        return loaded.pixels[:, :, 0].copy()

    monkeypatch.setattr(reviewjobs, "render_page", rendered)
    output = make_preview(source, 1, threading.Event(), policy=ColourPolicy.AUTO, view="output")
    assert shapes == [(160, 240, 3)]
    with Image.open(output) as image:
        assert image.size == (240, 160)
    assert raw.read_bytes() == original


def test_cancel_during_render_does_not_publish_a_partial_output_preview(out, monkeypatch):
    source = decided_draft(out)
    page = replace(source.pages[0], trim=TrimBox(0, 0, 0, 0, False))
    source = replace(source, pages=(page,))
    Image.new("RGB", (160, 240), "white").save(out / page.name, dpi=(300, 300))
    cancel = threading.Event()

    def rendered(loaded, mode):
        cancel.set()
        return np.zeros(loaded.pixels.shape[:2], dtype=np.uint8)

    monkeypatch.setattr(reviewjobs, "render_page", rendered)
    with pytest.raises(DocumentCancelledError):
        make_preview(source, 1, cancel, policy=ColourPolicy.AUTO, view="output")
    assert not (out / "previews").exists()


def test_confirmed_delete_removes_only_known_unchanged_output_variants(out, monkeypatch):
    side, page = opened(out)
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    folder = out / "previews"
    folder.mkdir()
    output = folder / "page-0001-output-bw-r1.jpg"
    unknown = folder / "page-0001-output-other-r1.jpg"
    output.write_bytes(b"synthetic")
    unknown.write_bytes(b"unrelated")
    page.worker.write_draft = lambda *args: None
    side.save()
    page.controller.on_finished(replace(clean_document(out), draft=side.state.draft, raw_dir=out))
    side.delete_originals(True)
    assert not output.exists()
    assert unknown.read_bytes() == b"unrelated"
