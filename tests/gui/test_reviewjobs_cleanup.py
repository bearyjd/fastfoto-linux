"""Output previews with and without paper cleanup, and the actual-pixel crop."""

import threading
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents import (
    CleanupPolicy,
    ColourMode,
    ColourPolicy,
    DocumentSettings,
    OcrMode,
    encode,
)
from fastfoto_linux.documents.cleanup import CleanupResult, CleanupStatus
from fastfoto_linux.documents.draft_edit import rotate, set_cleanup
from fastfoto_linux.documents.draft_store import open_draft
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.gui.reviewdelete import capture_originals, delete_originals
from fastfoto_linux.gui.reviewjobs import (
    PREVIEW_CROP_PX,
    PreviewRequest,
    make_preview,
    output_preview_names,
)
from fastfoto_linux.session.raw import list_pages
from tests.gui.test_reviewjobs import jobs_for

STRONG, OFF = CleanupPolicy.STRONG, CleanupPolicy.OFF
WIDTH, HEIGHT = 1300, 1150


def shaded_page(folder):
    """A synthetic grey sheet, 235 on the left to 205 on the right, with a few dark marks."""
    ramp = np.linspace(235, 205, WIDTH).astype(np.uint8)
    grey = np.tile(ramp, (HEIGHT, 1))
    for top in range(100, HEIGHT - 100, 90):
        grey[top : top + 8, 150 : WIDTH - 150 : 2] = 40
    Image.fromarray(np.dstack([grey] * 3)).save(folder / "page-0001.png", dpi=(300, 300))
    return folder


def analysed(folder, cleanup=STRONG):
    shaded_page(folder)
    settings = DocumentSettings(output_root=folder, ocr=OcrMode.OFF, cleanup=cleanup)
    return open_draft(folder, list_pages(folder), settings, fresh=True)


def expected(draft, cleanup, turns=0):
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))
    if turns:
        loaded = replace(loaded, pixels=np.rot90(loaded.pixels, -turns).copy())
    return render_page(loaded, ColourMode.GREY, cleanup)


def preview(draft, **options):
    options.setdefault("policy", ColourPolicy.GREY)
    return make_preview(draft, 1, threading.Event(), view="output", **options)


def test_the_synthetic_page_really_changes_under_strong(out):
    draft = analysed(out)
    assert draft.cleanup is STRONG
    assert not np.array_equal(expected(draft, STRONG), expected(draft, OFF))


def test_cleaned_output_names_the_level_and_decodes_to_the_cleaned_render(out):
    draft = analysed(out)
    path = preview(draft)
    assert path.name == "page-0001-output-grey-strong-r0.jpg"
    with Image.open(path) as image:
        assert image.size == (1300, 1150)
        shown = np.asarray(image.convert("L")).astype(int)
    plain = expected(draft, OFF).astype(int)
    cleaned = expected(draft, STRONG).astype(int)
    assert abs(shown - cleaned).mean() < abs(shown - plain).mean()


def test_turning_cleaned_off_renders_the_same_mode_and_turns_without_cleanup(out):
    draft = rotate(analysed(out), 1, 1)
    path = preview(draft, cleaned=False)
    assert path.name == "page-0001-output-grey-off-r1.jpg"
    with Image.open(path) as image:
        assert image.size == (HEIGHT, WIDTH)
        shown = np.asarray(image.convert("L")).astype(int)
    assert abs(shown - expected(draft, OFF, 1).astype(int)).mean() < 2


def test_a_page_override_beats_the_document_level_in_the_preview(out):
    draft = set_cleanup(analysed(out), 1, CleanupPolicy.LIGHT)
    assert preview(draft).name == "page-0001-output-grey-light-r0.jpg"
    off = set_cleanup(draft, 1, OFF)
    assert preview(off).name == "page-0001-output-grey-off-r0.jpg"


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
@pytest.mark.parametrize("centre", [(0, 0), (1000, 1000), (500, 500), (250, 800)])
def test_the_crop_is_the_lossless_actual_pixel_window_of_the_render(out, turns, centre):
    draft = analysed(out)
    draft = rotate(draft, 1, turns) if turns else draft
    path = preview(draft, crop=centre)
    assert path.name == f"page-0001-output-grey-strong-r{turns}-crop.png"
    full = expected(draft, STRONG, turns)
    height, width = full.shape
    cw, ch = min(PREVIEW_CROP_PX, width), min(PREVIEW_CROP_PX, height)
    left = min(max(0, centre[0] * width // 1000 - cw // 2), width - cw)
    top = min(max(0, centre[1] * height // 1000 - ch // 2), height - ch)
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size[0] <= PREVIEW_CROP_PX and image.size[1] <= PREVIEW_CROP_PX
        assert image.size == (cw, ch)
        assert np.array_equal(np.asarray(image), full[top : top + ch, left : left + cw])


def test_a_second_crop_replaces_the_first_in_the_same_file(out):
    draft = analysed(out)
    first = preview(draft, crop=(0, 0))
    with Image.open(first) as image:
        first_window = np.asarray(image).copy()
    second = preview(draft, crop=(1000, 1000))
    assert second == first  # one file per page, mode, level and turns
    full = expected(draft, STRONG)
    left, top = WIDTH - PREVIEW_CROP_PX, HEIGHT - PREVIEW_CROP_PX
    with Image.open(second) as image:
        window = np.asarray(image)
    assert np.array_equal(window, full[top:, left:])
    assert not np.array_equal(window, first_window)
    assert sorted(path.name for path in second.parent.iterdir()) == [second.name]


def test_the_crop_of_the_original_side_is_the_uncleaned_render(out):
    draft = analysed(out)
    path = preview(draft, cleaned=False, crop=(500, 500))
    assert path.name == "page-0001-output-grey-off-r0-crop.png"
    left, top = (WIDTH - PREVIEW_CROP_PX) // 2, (HEIGHT - PREVIEW_CROP_PX) // 2
    with Image.open(path) as image:
        assert np.array_equal(
            np.asarray(image),
            expected(draft, OFF)[top : top + PREVIEW_CROP_PX, left : left + PREVIEW_CROP_PX],
        )


@pytest.mark.parametrize("crop", [(1001, 5), (5, -1), (True, 5), (5, False), (5,), (1, 2, 3), "ab"])
def test_a_bad_crop_is_refused(out, crop):
    with pytest.raises(ValueError):
        PreviewRequest(analysed(out), 1, ColourPolicy.GREY, "output", True, crop)


def test_a_cancel_during_cleanup_publishes_nothing(out):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Exception, match="cancel"):
        make_preview(analysed(out), 1, cancel, policy=ColourPolicy.GREY, view="output")
    assert not (out / "previews").exists()


def test_the_whitelist_has_the_legacy_names_and_all_new_ones():
    names = output_preview_names(7)
    assert len(names) == len(set(names)) == 95
    assert "page-0007-output-grey-r2.jpg" in names
    assert "page-0007-output-bw-light-r3.jpg" in names
    assert "page-0007-output-colour-strong-r0-crop.png" in names
    assert "page-0007-output-grey-off-r1-crop.png" in names
    assert "page-0007-output-grey-medium-r1.jpg" not in names


def test_deleting_the_originals_removes_a_crop_preview(out):
    draft = analysed(out)
    crop = preview(draft, crop=(500, 500))
    saved = capture_originals(draft)
    delete_originals(saved)
    assert not crop.exists()


@pytest.mark.parametrize("status", list(CleanupStatus))
def test_worker_completion_carries_the_single_render_result(out, monkeypatch, status):
    draft = analysed(out)
    calls = []

    def clean(pixels, _dpi, _mode, _level, *, cancel):
        calls.append(cancel)
        return CleanupResult(status, pixels.copy() if status is CleanupStatus.APPLIED else None)

    monkeypatch.setattr(encode, "clean_pixels", clean)
    worker, tasks, sink = jobs_for(out)
    answers = []
    sink.on_review_preview = answers.append
    request = PreviewRequest(draft, 1, ColourPolicy.GREY, "output")
    worker.preview_page(request)
    cancel = threading.Event()
    tasks[0](cancel)()
    answer = answers[0]
    assert answer.cleanup_status is status
    assert answer.path.is_file() and not answer.error
    assert calls == [cancel]  # status comes from the render, never a second cleanup pass


@pytest.mark.parametrize(
    "view,cleaned,expected_status",
    [
        ("source", True, None),
        ("output", False, CleanupStatus.OFF),
    ],
)
def test_worker_source_and_without_cleanup_results(out, view, cleaned, expected_status):
    worker, tasks, sink = jobs_for(out)
    answers = []
    sink.on_review_preview = answers.append
    worker.preview_page(PreviewRequest(analysed(out), 1, ColourPolicy.GREY, view, cleaned))
    tasks[0](threading.Event())()
    assert answers[0].cleanup_status is expected_status


def test_real_dark_page_is_reported_as_skipped(out):
    draft = analysed(out)
    Image.new("RGB", (WIDTH, HEIGHT), (80, 80, 80)).save(out / draft.pages[0].name)
    worker, tasks, sink = jobs_for(out)
    answers = []
    sink.on_review_preview = answers.append
    worker.preview_page(PreviewRequest(draft, 1, ColourPolicy.GREY, "output"))
    tasks[0](threading.Event())()
    assert answers[0].cleanup_status is CleanupStatus.DARK


def test_cancel_after_cleanup_status_does_not_publish_pixels_or_status(out, monkeypatch):
    def clean(_pixels, _dpi, _mode, _level, *, cancel):
        cancel.set()
        return CleanupResult(CleanupStatus.DARK, None)

    monkeypatch.setattr(encode, "clean_pixels", clean)
    worker, tasks, sink = jobs_for(out)
    answers = []
    sink.on_review_preview = answers.append
    worker.preview_page(PreviewRequest(analysed(out), 1, ColourPolicy.GREY, "output"))
    tasks[0](threading.Event())()
    assert answers[0].path is None and "cancel" in answers[0].error
    assert answers[0].cleanup_status is None
    assert not (out / "previews").exists()
