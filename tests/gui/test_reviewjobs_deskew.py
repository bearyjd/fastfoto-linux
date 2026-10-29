"""Source previews of a straightened page, output names with an angle, the estimate job."""

import threading
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from fastfoto_linux.documents import DocumentError
from fastfoto_linux.documents.deskew import SkewEstimate, SkewStatus
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.page_crop import PageCrop, edited_page
from fastfoto_linux.gui import reviewjobs
from fastfoto_linux.gui.reviewjobs import PreviewRequest, ReviewJobs, make_preview
from fastfoto_linux.gui.reviewnames import crop_tag, is_output_preview_name
from tests.gui.crop_helpers import crop_draft
from tests.gui.doc_helpers import DocRecordingSink

HALF = PageCrop(5000, 0, 10_000, 10_000)


def with_edit(draft, **edit):
    return replace(draft, edits={1: PageEdit(**edit)})


def source_image(draft):
    sizes = []
    request = PreviewRequest(draft, 1)
    pixels, suffix = reviewjobs._preview_image(
        request, threading.Event(), on_size=lambda *size: sizes.append(size)
    )
    return pixels, suffix, sizes


def test_a_source_preview_without_an_angle_is_unchanged(out):
    draft = crop_draft(out)
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))
    pixels, suffix, _sizes = source_image(draft)
    assert suffix == "" and np.array_equal(pixels, loaded.pixels)
    path = make_preview(draft, 1, threading.Event())
    assert path.name == "page-0001.jpg"


@pytest.mark.parametrize(("tenths", "suffix"), [(41, "-straight-p041"), (-41, "-straight-m041")])
def test_a_source_preview_with_an_angle_is_the_straightened_page(out, tenths, suffix):
    draft = with_edit(crop_draft(out), deskew_tenths=tenths)
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))
    expected = edited_page(loaded, PageEdit(deskew_tenths=tenths)).pixels
    pixels, found, sizes = source_image(draft)
    assert found == suffix and np.array_equal(pixels, expected)
    assert not np.array_equal(pixels, loaded.pixels)
    # The frame the crop is stored in does not change.
    assert sizes == [(loaded.pixels.shape[1], loaded.pixels.shape[0], loaded.dpi)]
    assert make_preview(draft, 1, threading.Event()).name == f"page-0001{suffix}.jpg"


def test_the_source_preview_ignores_the_crop_and_turns_of_the_edit(out):
    draft = with_edit(crop_draft(out), deskew_tenths=41, crop=HALF, quarter_turns=1)
    pixels, suffix, sizes = source_image(draft)
    assert suffix == "-straight-p041"
    assert pixels.shape[:2] == (1800, 1200) and sizes[0][:2] == (1200, 1800)


def test_a_page_too_large_to_straighten_keeps_the_plain_name(out, monkeypatch):
    monkeypatch.setattr("fastfoto_linux.documents.page_crop.work_too_large", lambda *a: True)
    draft = with_edit(crop_draft(out), deskew_tenths=41)
    _pixels, suffix, _sizes = source_image(draft)
    assert suffix == ""
    assert make_preview(draft, 1, threading.Event()).name == "page-0001.jpg"


def test_an_output_name_with_an_angle_and_no_crop_carries_the_hash(out):
    draft = with_edit(crop_draft(out), deskew_tenths=41)
    path = make_preview(draft, 1, threading.Event(), policy="grey", view="output")
    assert path.name == f"page-0001-output-grey-off-r0-c{crop_tag(None, 0, 41)}.jpg"
    assert is_output_preview_name(1, path.name)


def test_an_output_name_with_an_angle_and_a_crop_differs_from_the_crop_alone(out):
    both = with_edit(crop_draft(out), deskew_tenths=41, crop=HALF)
    crop_only = with_edit(crop_draft(out), crop=HALF)
    one = make_preview(both, 1, threading.Event(), policy="grey", view="output")
    two = make_preview(crop_only, 1, threading.Event(), policy="grey", view="output")
    assert one.name != two.name
    assert two.name == f"page-0001-output-grey-off-r0-c{crop_tag(HALF, 0)}.jpg"


def test_an_output_name_with_neither_is_unchanged(out):
    path = make_preview(crop_draft(out), 1, threading.Event(), policy="grey", view="output")
    assert path.name == "page-0001-output-grey-off-r0.jpg"


# -- the estimate job ------------------------------------------------------------------------


def estimate_jobs(estimate):
    jobs, sink = [], DocRecordingSink()
    tools = SimpleNamespace(
        open_review=None, write_review=None, preview_review=None, estimate_review=estimate
    )
    return ReviewJobs(sink, jobs.append, tools), jobs, sink


def run_estimate(out, estimate):
    worker, jobs, sink = estimate_jobs(estimate)
    draft = crop_draft(out)
    worker.estimate_page(draft, 1)
    jobs[0](threading.Event())()
    return draft, sink.value("review_deskew")


def test_the_job_answers_with_the_draft_the_page_and_the_estimate(out):
    draft, answer = run_estimate(out, lambda *a, **k: SkewEstimate(SkewStatus.ESTIMATED, 41))
    assert answer.draft is draft and answer.number == 1
    assert (answer.status, answer.tenths) == (SkewStatus.ESTIMATED, 41)


def test_the_job_passes_the_cancel_event_to_the_estimate(out):
    seen = []

    def estimate(draft, number, *, cancel=None):
        seen.append((draft, number, cancel))
        return SkewEstimate(SkewStatus.LEVEL)

    draft, _answer = run_estimate(out, estimate)
    assert seen[0][:2] == (draft, 1) and isinstance(seen[0][2], threading.Event)


@pytest.mark.parametrize(
    "error", [DocumentError("x"), OSError("x"), ValueError("x"), RuntimeError("x")]
)
def test_an_error_is_an_error_marker_with_no_message(out, error):
    secret = str(out / "page-0001.png")

    def estimate(*args, **kwargs):
        raise type(error)(f"cannot read {secret}")

    _draft, answer = run_estimate(out, estimate)
    assert answer.status == reviewjobs.DESKEW_ERROR and answer.tenths == 0
    assert str(out) not in repr(answer.status) + str(answer.tenths)
    assert secret not in repr(answer).replace(repr(answer.draft), "")
