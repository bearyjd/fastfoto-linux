"""Output previews with and without Remove specks: the render, the names, the whitelist."""

import threading
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents import (
    ColourMode,
    ColourPolicy,
    DespeckleStatus,
    DocumentSettings,
    OcrMode,
)
from fastfoto_linux.documents.draft_edit import (
    rotate,
    set_cleanup,
    set_crop,
    set_document_despeckle,
)
from fastfoto_linux.documents.draft_store import open_draft
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.modes import CleanupPolicy
from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.gui.reviewdelete import capture_originals, delete_originals
from fastfoto_linux.gui.reviewjobs import PreviewRequest, make_preview, output_preview_names
from fastfoto_linux.gui.reviewnames import is_output_preview_name
from fastfoto_linux.session.raw import list_pages
from tests.gui.test_reviewjobs import jobs_for

WIDTH, HEIGHT = 600, 800
LIGHT, OFF = CleanupPolicy.LIGHT, CleanupPolicy.OFF
BW, GREY = ColourPolicy.BW, ColourPolicy.GREY


def dusty_page(folder, *, specks=True, dpi=300):
    """White paper, a few stems of ink and isolated 2 px specks far (over 2.5 mm) from any ink."""
    grey = np.full((HEIGHT, WIDTH), 255, np.uint8)
    for column in (100, 160, 220):
        grey[300:340, column : column + 4] = 0
    for row, column in ((100, 400), (500, 450), (650, 120), (120, 120)) if specks else ():
        grey[row : row + 2, column : column + 2] = 0
    Image.fromarray(np.dstack([grey] * 3)).save(folder / "page-0001.png", dpi=(dpi, dpi))
    return folder


def analysed(folder, *, despeckle=True, specks=True, dpi=300):
    dusty_page(folder, specks=specks, dpi=dpi)
    settings = DocumentSettings(output_root=folder, ocr=OcrMode.OFF)
    draft = open_draft(folder, list_pages(folder), settings, fresh=True)
    return set_document_despeckle(draft, True) if despeckle else draft


def expected(draft, *, despeckle, turns=0):
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))
    if turns:
        loaded = replace(loaded, pixels=np.rot90(loaded.pixels, -turns).copy())
    return render_page(loaded, ColourMode.BW, OFF, despeckle=despeckle)


def preview(draft, **options):
    options.setdefault("policy", BW)
    options.setdefault("crop", (500, 500))
    return make_preview(draft, 1, threading.Event(), view="output", **options)


def decoded(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("L"))


def test_the_fixture_really_has_specks_to_remove(out):
    draft = analysed(out)
    assert not np.array_equal(expected(draft, despeckle=True), expected(draft, despeckle=False))


def test_the_cleaned_side_is_the_despeckled_render_and_names_it(out):
    draft = analysed(out)
    path = preview(draft)
    assert path.name == "page-0001-output-bw-off-r0-s-crop.png"
    assert np.array_equal(decoded(path), expected(draft, despeckle=True))


def test_the_original_side_keeps_the_mode_turns_and_crop_but_not_the_specks(out):
    draft = rotate(analysed(out), 1, 1)
    path = preview(draft, cleaned=False)
    assert path.name == "page-0001-output-bw-off-r1-crop.png"
    assert np.array_equal(decoded(path), expected(draft, despeckle=False, turns=1))


def test_a_bw_page_with_a_cleanup_level_is_named_off_when_despeckled(out):
    draft = set_cleanup(analysed(out), 1, LIGHT)
    assert preview(draft).name == "page-0001-output-bw-off-r0-s-crop.png"
    assert preview(draft, cleaned=False).name == "page-0001-output-bw-off-r0-crop.png"


def test_the_switch_off_changes_nothing_in_the_name_or_the_pixels(out):
    draft = analysed(out, despeckle=False)
    path = preview(draft)
    assert path.name == "page-0001-output-bw-off-r0-crop.png"
    assert np.array_equal(decoded(path), expected(draft, despeckle=False))


def test_a_grey_page_is_not_changed_and_has_no_s_in_its_name(out):
    on, off = analysed(out), analysed(out, despeckle=False)
    shown_on = preview(on, policy=GREY)
    assert shown_on.name == "page-0001-output-grey-off-r0-crop.png"
    assert np.array_equal(decoded(shown_on), decoded(preview(off, policy=GREY)))


def test_the_uncropped_jpeg_is_named_the_same_way(out):
    draft = analysed(out)
    assert preview(draft, crop=None).name == "page-0001-output-bw-off-r0-s.jpg"
    assert preview(draft, crop=None, cleaned=False).name == "page-0001-output-bw-off-r0.jpg"


def test_a_cropped_page_names_the_s_before_the_crop_tag(out):
    draft = set_crop(analysed(out), 1, PageCrop(500, 500, 9500, 9500))
    name = preview(draft, crop=None).name
    assert is_output_preview_name(1, name)
    assert name.startswith("page-0001-output-bw-off-r0-s-c") and name.endswith(".jpg")
    assert "-s-" not in preview(draft, crop=None, cleaned=False).name


def test_the_worker_job_renders_the_request_draft(out):
    worker, tasks, sink = jobs_for(out)
    answers = []
    sink.on_review_preview = answers.append
    worker.preview_page(PreviewRequest(analysed(out), 1, BW, "output", True, (500, 500)))
    tasks[0](threading.Event())()
    assert answers[0].path.name == "page-0001-output-bw-off-r0-s-crop.png"


# -- the names -----------------------------------------------------------------------------------


def test_the_whitelist_gains_exactly_the_eight_black_and_white_s_names():
    names = output_preview_names(7)
    assert len(names) == len(set(names)) == 95
    added = {name for name in names if name.endswith(("-s.jpg", "-s-crop.png"))}
    assert added == {
        f"page-0007-output-bw-off-r{turns}-s{extension}"
        for turns in range(4)
        for extension in (".jpg", "-crop.png")
    }
    assert "page-0007-output-grey-off-r0-s.jpg" not in names


@pytest.mark.parametrize("extension", [".jpg", "-crop.png"])
@pytest.mark.parametrize("stem", ["bw-off-r0-s", "bw-light-r3-s", "bw-strong-r1"])
def test_a_cropped_name_with_or_without_s_is_accepted(stem, extension):
    assert is_output_preview_name(1, f"page-0001-output-{stem}-c0123456789ab{extension}")


@pytest.mark.parametrize(
    "name",
    [
        "page-0001-output-grey-off-r0-s-c0123456789ab.jpg",
        "page-0001-output-colour-off-r0-s-c0123456789ab.jpg",
        "page-0001-output-bw-off-r0-ss-c0123456789ab.jpg",
        "page-0001-output-bw-off-r0-S-c0123456789ab.jpg",
        "page-0001-output-bw-off-r0-s-s-c0123456789ab.jpg",
        "page-0001-output-bw-off-r0-c0123456789ab-s.jpg",
        "page-0001-output-bw-off-r0-s-c0123456789ab.JPG",
        "../page-0001-output-bw-off-r0-s-c0123456789ab.jpg",
        "page-0001-output-bw-off-r0-s/../x-c0123456789ab.jpg",
        "page-0002-output-bw-off-r0-s-c0123456789ab.jpg",
    ],
)
def test_other_shapes_are_not_preview_names(name):
    assert not is_output_preview_name(1, name)


def test_deleting_the_originals_removes_the_s_previews(out):
    draft = analysed(out)
    plain, actual = preview(draft, crop=None), preview(draft)
    cropped = preview(set_crop(draft, 1, PageCrop(500, 500, 9500, 9500)), crop=None)
    assert plain.name == "page-0001-output-bw-off-r0-s.jpg"
    assert {plain.name, actual.name} <= set(output_preview_names(1))
    assert is_output_preview_name(1, cropped.name) and "-s-c" in cropped.name
    saved = capture_originals(draft)
    delete_originals(saved)
    assert not plain.exists() and not actual.exists() and not cropped.exists()


# -- what the render did is reported, the name is not ---------------------------------------------


def worker_status(draft, out, **options):
    worker, tasks, sink = jobs_for(out)
    answers = []
    sink.on_review_preview = answers.append
    options.setdefault("crop", (500, 500))
    worker.preview_page(PreviewRequest(draft, 1, BW, "output", **options))
    tasks[0](threading.Event())()
    return answers[0]


def test_an_applied_page_reports_applied(out):
    answer = worker_status(analysed(out), out)
    assert answer.despeckle_status is DespeckleStatus.APPLIED


def test_a_low_dpi_page_reports_why_nothing_changed_and_keeps_the_request_based_name(out):
    draft = analysed(out, dpi=100)
    answer = worker_status(draft, out)
    assert answer.despeckle_status is DespeckleStatus.LOW_DPI
    assert answer.path.name == "page-0001-output-bw-off-r0-s-crop.png"  # named by the request
    assert np.array_equal(decoded(answer.path), expected(draft, despeckle=False))


def test_a_page_with_nothing_to_remove_reports_none(out):
    answer = worker_status(analysed(out, specks=False), out)
    assert answer.despeckle_status is DespeckleStatus.NONE


def test_the_original_side_and_a_switch_that_is_off_report_off(out):
    assert worker_status(analysed(out), out, cleaned=False).despeckle_status is DespeckleStatus.OFF
    off = analysed(out, despeckle=False)
    assert worker_status(off, out).despeckle_status is DespeckleStatus.OFF
