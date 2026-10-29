"""Writing a straightened page: the PDF holds the previewed pixels, cached bytes are not reused."""

from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from fastfoto_linux.documents.cleanup import CleanupStatus
from fastfoto_linux.documents.despeckle import DespeckleStatus
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_edit import rotate, set_crop, set_deskew
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from fastfoto_linux.documents.page_crop import PageCrop, edited_page
from fastfoto_linux.documents.write import write_document
from tests.documents.crop_helpers import crop_draft
from tests.documents.deskew_fixtures import loaded, skewed, text_page
from tests.documents.test_crop_write import Spy, preview_pixels, settings_of

CROP = PageCrop(1000, 2000, 7000, 9000)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.mark.parametrize("cleanup", [CleanupPolicy.OFF, CleanupPolicy.LIGHT])
@pytest.mark.parametrize("kind", [ColourMode.GREY, ColourMode.COLOUR])
@pytest.mark.parametrize("turns", [0, 1])
def test_the_written_pixels_are_the_previewed_pixels(  # noqa: PLR0913, PLR0917 - the grid
    tmp_path: Path,
    out: Path,
    monkeypatch,
    cleanup,
    kind,
    turns,
) -> None:
    draft = replace(crop_draft(tmp_path / "raw", kind), cleanup=cleanup)
    draft = rotate(set_deskew(draft, 1, -41), 1, turns)
    expected = preview_pixels(draft, kind, cleanup)
    spy = Spy(monkeypatch)
    write_document(draft, settings_of(out, kind))
    assert len(spy.jpegs) == 1
    assert np.array_equal(spy.jpegs[0], expected)


def test_a_straightened_page_does_not_reuse_the_bytes_it_carries(
    tmp_path: Path,
    out: Path,
    monkeypatch,
) -> None:
    kind = ColourMode.GREY
    draft = set_deskew(crop_draft(tmp_path / "raw", kind, encoded=kind), 1, 12)
    spy = Spy(monkeypatch)
    calls: list[int] = []
    write_document(draft, settings_of(out, kind), on_page=lambda n, _: calls.append(n))
    assert (spy.encodes, calls) == (1, [1])


def test_clearing_the_angle_brings_the_cached_bytes_back(
    tmp_path: Path,
    out: Path,
    monkeypatch,
) -> None:
    kind = ColourMode.GREY
    draft = crop_draft(tmp_path / "raw", kind, encoded=kind)
    draft = set_deskew(set_deskew(draft, 1, 12), 1, None)
    spy = Spy(monkeypatch)
    write_document(draft, settings_of(out, kind))
    assert spy.encodes == 0


def test_an_uncropped_page_with_a_crop_made_after_the_angle_is_written_cropped(
    tmp_path: Path,
    out: Path,
    monkeypatch,
) -> None:
    kind = ColourMode.GREY
    draft = set_crop(set_deskew(crop_draft(tmp_path / "raw", kind), 1, 30), 1, CROP)
    spy = Spy(monkeypatch)
    write_document(draft, settings_of(out, kind))
    assert np.array_equal(spy.jpegs[0], preview_pixels(draft, kind, CleanupPolicy.OFF))


def test_cleanup_still_applies_to_a_straightened_page() -> None:
    page = loaded(skewed(text_page(np.random.default_rng(2)), 50))
    straight = edited_page(page, PageEdit(deskew_tenths=-50))
    seen: list[CleanupStatus] = []
    render_page(straight, ColourMode.GREY, CleanupPolicy.LIGHT, on_cleanup=seen.append)
    assert seen == [CleanupStatus.APPLIED]


def _specks(white_black: np.ndarray, biggest: int = 12) -> int:
    _, _, stats, _ = cv2.connectedComponentsWithStats((white_black == 0).astype(np.uint8))
    return int((stats[1:, cv2.CC_STAT_AREA] <= biggest).sum())


def test_a_straightened_black_and_white_page_gains_no_specks() -> None:
    base = text_page(np.random.default_rng(6))
    seen: list[DespeckleStatus] = []
    plain = render_page(loaded(base), ColourMode.BW, despeckle=True, on_despeckle=seen.append)
    tilted = loaded(skewed(base, 50))
    straight = edited_page(tilted, PageEdit(deskew_tenths=-50))
    after = render_page(straight, ColourMode.BW, despeckle=True, on_despeckle=seen.append)
    assert _specks(after) <= _specks(plain)
    assert seen[-1] is seen[0]  # despeckle treated both pages alike
