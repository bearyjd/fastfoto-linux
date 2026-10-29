"""Names of straightened source previews and of output previews with an angle."""

import os

import pytest

from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.gui.reviewdelete import capture_originals
from fastfoto_linux.gui.reviewnames import (
    PREVIEW_DIR,
    crop_tag,
    cropped_previews,
    is_source_preview_name,
    preview_name_allowed,
)
from tests.gui.review_helpers import draft

HALF = PageCrop(5000, 0, 10_000, 10_000)
GOLDEN = (
    (HALF, 0, "4e636055f156"),
    (HALF, 1, "78136f244a40"),
    (PageCrop(0, 0, 5000, 10_000), 2, "3483d2ba8a77"),
)


@pytest.mark.parametrize(("crop", "turns", "golden"), GOLDEN)
def test_a_name_without_an_angle_is_the_name_it_always_was(crop, turns, golden):
    assert crop_tag(crop, turns) == crop_tag(crop, turns, None) == golden


def test_an_angle_changes_the_tag_with_or_without_a_crop():
    plain = crop_tag(HALF, 0)
    with_angle = crop_tag(HALF, 0, 41)
    assert with_angle != plain
    assert crop_tag(None, 0, 41) not in {plain, with_angle}
    assert crop_tag(HALF, 0, -41) != with_angle
    assert crop_tag(None, 1, 41) != crop_tag(None, 0, 41)
    assert len(crop_tag(None, 0, 41)) == 12


@pytest.mark.parametrize(
    "name",
    [
        "page-0001-straight-p001.jpg",
        "page-0001-straight-m100.jpg",
        "page-0001-straight-p041.jpg",
        "page-0001.jpg",
    ],
)
def test_the_source_names_accepted(name):
    assert is_source_preview_name(1, name)


@pytest.mark.parametrize(
    "name",
    [
        "page-0001-straight-p000.jpg",
        "page-0001-straight-m000.jpg",
        "page-0001-straight-p101.jpg",
        "page-0001-straight-p41.jpg",
        "page-0001-straight-+041.jpg",
        "page-0001-straight-p041.png",
        "../page-0001-straight-p041.jpg",
        "/page-0001-straight-p041.jpg",
        "page-0002-straight-p041.jpg",
        "page-0001-straight-p041.jpg/",
        "x/page-0001.jpg",
        None,
        41,
        b"page-0001.jpg",
    ],
)
def test_the_source_names_refused(name):
    assert not is_source_preview_name(1, name)


@pytest.mark.parametrize("number", [True, False, 0, 10_000, "1", 1.0, None])
def test_the_source_name_refuses_a_page_number_that_is_not_a_page(number):
    assert not is_source_preview_name(number, "page-0001.jpg")
    assert not is_source_preview_name(number, "page-0001-straight-p041.jpg")


def test_preview_name_allowed_keeps_the_accept_sets_of_both_views():
    assert preview_name_allowed(1, "source", "page-0001.jpg")
    assert preview_name_allowed(1, "source", "page-0001-straight-m041.jpg")
    assert not preview_name_allowed(1, "source", "page-0001-output-grey-off-r0.jpg")
    assert not preview_name_allowed(2, "source", "page-0001.jpg")
    assert preview_name_allowed(1, "output", "page-0001-output-grey-off-r0.jpg")
    cropped = f"page-0001-output-grey-off-r0-c{crop_tag(HALF, 0)}.jpg"
    assert preview_name_allowed(1, "output", cropped)
    assert preview_name_allowed(
        1, "output", f"page-0001-output-bw-off-r0-c{crop_tag(None, 0, 41)}.jpg"
    )
    assert not preview_name_allowed(1, "output", "page-0001.jpg")
    assert not preview_name_allowed(1, "output", "page-0001-straight-p041.jpg")


def test_cropped_previews_lists_straight_files_but_not_links_or_folders(tmp_path):
    (tmp_path / "page-0001-straight-p041.jpg").write_bytes(b"x")
    (tmp_path / "page-0001-straight-m041.jpg").mkdir()
    (tmp_path / "target").write_bytes(b"x")
    os.symlink(tmp_path / "target", tmp_path / "page-0001-straight-p042.jpg")
    (tmp_path / "page-0002-straight-p041.jpg").write_bytes(b"x")
    assert cropped_previews(tmp_path, 1) == [tmp_path / "page-0001-straight-p041.jpg"]


def test_capture_originals_lists_a_straight_preview(out):
    source = draft(out)
    for page in source.pages:
        (out / page.name).write_bytes(b"synthetic!")
        os.utime(out / page.name, ns=(1, 1))
    previews = out / PREVIEW_DIR
    previews.mkdir()
    (previews / "page-0001-straight-p041.jpg").write_bytes(b"x")
    saved = capture_originals(source)
    assert f"{PREVIEW_DIR}/page-0001-straight-p041.jpg" in {name for name, _ in saved.artifacts}


def test_a_tag_needs_a_crop_or_an_angle():
    with pytest.raises(ValueError):
        crop_tag(None, 0)
