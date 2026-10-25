"""Cropped previews: the same pixels as the PDF, server-built names, bounded and link-safe."""

import os
import re
import threading
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.page_crop import PageCrop, edited_page
from fastfoto_linux.gui import reviewjobs
from fastfoto_linux.gui.reviewdelete import capture_originals, delete_originals
from fastfoto_linux.gui.reviewjobs import PREVIEW_DIR, make_preview
from fastfoto_linux.gui.reviewnames import (
    MAX_CROP_PREVIEWS,
    checked_preview_path,
    crop_tag,
    is_output_preview_name,
    output_preview_names,
)
from tests.gui.crop_helpers import DPI, HEIGHT, WIDTH, crop_draft

RIGHT_HALF = PageCrop(5000, 0, 10_000, 10_000)


def edited(draft, crop, turns=0):
    edit = PageEdit(quarter_turns=turns, crop=crop)
    return replace(draft, edits={1: edit})


def test_the_output_preview_is_the_edited_page_cropped_then_turned(out):
    draft = edited(crop_draft(out), RIGHT_HALF, turns=1)
    path = make_preview(draft, 1, threading.Event(), policy="grey", view="output")
    with Image.open(path) as image:
        assert image.size == (1600, 533)  # 600 x 1800 turned to 1800 x 600, bounded to 1600
        pixels = np.asarray(image.convert("L"))
    assert pixels.min() > 240  # the black half is gone
    assert "-r1-c" in path.name


def test_preview_and_pdf_share_edited_page(out, monkeypatch):
    draft = edited(crop_draft(out), RIGHT_HALF)
    seen = []
    real = reviewjobs.edited_page

    def spy(trimmed, edit):
        seen.append(edit.crop)
        return real(trimmed, edit)

    monkeypatch.setattr(reviewjobs, "edited_page", spy)
    make_preview(draft, 1, threading.Event(), view="output")
    assert seen == [RIGHT_HALF]
    page = draft.pages[0]
    loaded = page.trim.apply(load_page(draft.raw_dir / page.name, fallback_dpi=page.dpi))
    assert edited_page(loaded, draft.edits[1]).pixels.shape[:2] == (HEIGHT, WIDTH // 2)


def test_the_source_view_stays_uncropped_and_reports_size_and_dpi(out):
    draft = edited(crop_draft(out), RIGHT_HALF)
    sizes = []
    path = make_preview(draft, 1, threading.Event(), on_size=lambda *args: sizes.append(args))
    assert sizes == [(WIDTH, HEIGHT, DPI)]
    assert path.name == "page-0001.jpg"
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("L"))
    assert pixels.min() < 20 and pixels.max() > 240


def test_an_uncropped_output_keeps_its_fixed_name(out):
    path = make_preview(crop_draft(out), 1, threading.Event(), view="output")
    assert path.name in output_preview_names(1)


def test_a_cropped_name_is_built_from_the_page_the_mode_and_a_short_hash(out):
    draft = edited(crop_draft(out), RIGHT_HALF)
    path = make_preview(draft, 1, threading.Event(), policy="grey", view="output")
    assert re.fullmatch(r"page-0001-output-grey-off-r0-c[0-9a-f]{12}\.jpg", path.name)
    assert is_output_preview_name(1, path.name)
    assert not is_output_preview_name(2, path.name)
    assert path.name not in output_preview_names(1)
    assert path.parent == out / PREVIEW_DIR


def test_the_hash_depends_on_the_crop_and_the_turns_only():
    base = crop_tag(RIGHT_HALF, 0)
    assert re.fullmatch(r"[0-9a-f]{12}", base)
    assert crop_tag(RIGHT_HALF, 0) == base
    assert crop_tag(RIGHT_HALF, 1) != base
    assert crop_tag(PageCrop(5000, 0, 10_000, 9999), 0) != base


@pytest.mark.parametrize(
    "name",
    [
        "../page-0001-output-grey-off-r0-c0123456789ab.jpg",
        "page-0001-output-grey-off-r0-c0123456789ab.jpg/../x",
        "page-0001-output-grey-off-r0-c0123456789AB.jpg",
        "page-0001-output-grey-off-r0-c0123456789a.jpg",
        "page-0001-output-grey-off-r0-c0123456789abc.jpg",
        "page-0001-output-grey-off-r4-c0123456789ab.jpg",
        "page-0001-output-grey-off-r0-c0123456789ab.png",
        "page-0001-output-grey-off-r0-c0123456789ab.jpg\n",
        "page-0001-output-grey-off-r0-c10001.jpg",
        "page-0001-output-pink-off-r0-c0123456789ab.jpg",
        "page-0001-output-grey-heavy-r0-c0123456789ab.jpg",
        "/etc/passwd",
        "",
    ],
)
def test_names_outside_the_pattern_are_refused(name):
    assert not is_output_preview_name(1, name)


@pytest.mark.parametrize("suffix", [".jpg", "-crop.png"])
def test_the_patterns_for_both_preview_kinds_are_accepted(suffix):
    assert is_output_preview_name(1, f"page-0001-output-bw-strong-r3-c0123456789ab{suffix}")


def crops(count):
    return [PageCrop(0, 0, 10_000 - i, 10_000) for i in range(count)]


def test_the_cached_crop_previews_are_bounded_and_the_oldest_go(out):
    draft = crop_draft(out)
    paths = []
    for i, crop in enumerate(crops(MAX_CROP_PREVIEWS + 4)):
        path = make_preview(edited(draft, crop), 1, threading.Event(), view="output")
        os.utime(path, (1000 + i, 1000 + i))
        paths.append(path)
    left = [p for p in (out / PREVIEW_DIR).iterdir() if is_output_preview_name(1, p.name)]
    assert len(left) <= MAX_CROP_PREVIEWS
    assert paths[-1].exists() and not paths[0].exists()


def test_another_pages_and_unrelated_previews_are_not_evicted(out):
    draft = crop_draft(out)
    folder = out / PREVIEW_DIR
    folder.mkdir()
    keep = [folder / "notes.txt", folder / "page-0002-output-grey-off-r0-c0123456789ab.jpg"]
    for path in keep:
        path.write_bytes(b"x")
        os.utime(path, (1, 1))
    for crop in crops(MAX_CROP_PREVIEWS + 3):
        make_preview(edited(draft, crop), 1, threading.Event(), view="output")
    assert all(path.exists() for path in keep)


def test_a_planted_link_at_the_preview_name_is_replaced_not_followed(out):
    draft = edited(crop_draft(out), RIGHT_HALF)
    victim = out / "victim.txt"
    victim.write_bytes(b"precious")
    folder = out / PREVIEW_DIR
    folder.mkdir()
    name = f"page-0001-output-grey-off-r0-c{crop_tag(RIGHT_HALF, 0)}.jpg"
    (folder / name).symlink_to(victim)
    path = make_preview(draft, 1, threading.Event(), policy="grey", view="output")
    assert path.name == name and not path.is_symlink()
    assert victim.read_bytes() == b"precious"


def test_a_previews_folder_that_is_a_link_is_refused(out):
    elsewhere = out / "elsewhere"
    elsewhere.mkdir()
    (out / PREVIEW_DIR).symlink_to(elsewhere)
    with pytest.raises(OSError):
        make_preview(edited(crop_draft(out), RIGHT_HALF), 1, threading.Event(), view="output")
    assert list(elsewhere.iterdir()) == []


def test_eviction_never_follows_a_link_out_of_the_previews_folder(out):
    draft = crop_draft(out)
    victim = out / "victim.txt"
    victim.write_bytes(b"precious")
    folder = out / PREVIEW_DIR
    folder.mkdir()
    link = folder / "page-0001-output-grey-off-r0-c0123456789ab.jpg"
    link.symlink_to(victim)
    os.utime(link, (1, 1), follow_symlinks=False)
    for crop in crops(MAX_CROP_PREVIEWS + 2):
        make_preview(edited(draft, crop), 1, threading.Event(), view="output")
    assert victim.read_bytes() == b"precious"
    assert link.is_symlink()  # not counted, not removed


def test_deleting_originals_removes_the_cropped_previews_and_nothing_else(out):
    draft = edited(crop_draft(out), RIGHT_HALF)
    path = make_preview(draft, 1, threading.Event(), view="output")
    folder = out / PREVIEW_DIR
    other = folder / "notes.txt"
    other.write_bytes(b"mine")
    victim = out / "victim.txt"
    victim.write_bytes(b"precious")
    link = folder / "page-0001-output-bw-light-r1-c0123456789ab.jpg"
    link.symlink_to(victim)
    delete_originals(capture_originals(draft))
    assert not path.exists()
    assert other.read_bytes() == b"mine" and victim.read_bytes() == b"precious"
    assert link.is_symlink()


@pytest.mark.parametrize("name", ["../outside.jpg", "sub/../../outside.jpg", "a/b.jpg", "/abs.jpg"])
def test_a_name_that_leaves_the_previews_folder_is_refused_before_any_write(out, name):
    folder = out / PREVIEW_DIR
    folder.mkdir()
    with pytest.raises(ValueError):
        checked_preview_path(folder, name)
