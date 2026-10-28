"""PageEdit.deskew_tenths, draft_edit.set_deskew and the order of edited_page."""

from dataclasses import replace

import numpy as np
import pytest

from fastfoto_linux.documents import cleanup
from fastfoto_linux.documents.deskew_warp import deskewed
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_edit import rotate, set_crop, set_deskew
from fastfoto_linux.documents.errors import DocumentEditError
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.page_crop import PageCrop, crop_box, edited_page
from fastfoto_linux.photo_edits.geometry import apply_geometry
from fastfoto_linux.photo_edits.model import PhotoGeometry
from tests.documents.edit_helpers import draft_of

CROP = PageCrop(1000, 2000, 9000, 8000)


def _page() -> LoadedPage:
    rng = np.random.default_rng(0)
    return LoadedPage(rng.integers(0, 256, (120, 90, 3), dtype=np.uint8), ColourMode.COLOUR, 100)


def test_a_page_edit_holds_an_angle_or_nothing() -> None:
    assert PageEdit().deskew_tenths is None
    assert PageEdit(deskew_tenths=-100).deskew_tenths == -100
    assert PageEdit(None, 0, None, None, None, 7).deskew_tenths == 7  # appended last


@pytest.mark.parametrize("bad", [0, 101, -101, True, 1.5, "3"])
def test_a_bad_angle_is_refused_by_the_edit(bad) -> None:
    with pytest.raises(ValueError, match="deskew"):
        PageEdit(deskew_tenths=bad)


def test_set_deskew_is_pure_and_keeps_the_rest_of_the_edit() -> None:
    draft = rotate(draft_of(3), 2, 1)
    out = set_deskew(draft, 2, 14)
    assert out.edits[2].deskew_tenths == 14
    assert out.edits[2].quarter_turns == 1
    assert draft.edits[2].deskew_tenths is None


def test_zero_and_none_clear_the_angle_and_drop_a_default_edit() -> None:
    draft = draft_of(3)
    with_angle = set_deskew(draft, 1, -9)
    assert set_deskew(with_angle, 1, 0) == draft
    assert set_deskew(with_angle, 1, None) == draft


@pytest.mark.parametrize("bad", [101, -101, True, 2.5, "1"])
def test_set_deskew_refuses_what_is_no_angle(bad) -> None:
    with pytest.raises(DocumentEditError):
        set_deskew(draft_of(2), 1, bad)


def test_set_deskew_refuses_a_page_that_is_not_there() -> None:
    with pytest.raises(DocumentEditError):
        set_deskew(draft_of(2), 3, 5)


def test_a_changed_angle_clears_the_crop_and_the_same_angle_keeps_it() -> None:
    draft = set_deskew(draft_of(2), 1, 10)
    cropped = set_crop(draft, 1, CROP)
    assert set_deskew(cropped, 1, 10).edits[1].crop == CROP
    assert set_deskew(cropped, 1, 11).edits[1].crop is None
    assert set_deskew(cropped, 1, None).edits[1].crop is None
    assert set_deskew(set_crop(draft_of(2), 1, CROP), 1, 10).edits[1].crop is None


def test_without_an_angle_the_page_is_the_same_object() -> None:
    page = _page()
    assert edited_page(page, PageEdit()) is page


def test_the_page_is_deskewed_then_cropped_then_turned() -> None:
    page = _page()
    edit = PageEdit(quarter_turns=1, crop=CROP, deskew_tenths=-37)
    straight = deskewed(page.pixels, -37, page.kind)
    box = crop_box(90, 120, 100, CROP)
    expected = apply_geometry(straight, PhotoGeometry(quarter_turns=1, crop=box))
    out = edited_page(page, edit)
    assert np.array_equal(out.pixels, expected)
    assert (out.kind, out.dpi) == (page.kind, page.dpi)


def test_an_angle_alone_keeps_the_frame_and_does_not_touch_the_input() -> None:
    page = _page()
    before = page.pixels.copy()
    out = edited_page(page, PageEdit(deskew_tenths=50))
    assert out.pixels.shape == page.pixels.shape
    assert not np.array_equal(out.pixels, page.pixels)
    assert np.array_equal(page.pixels, before)


def test_a_page_too_large_for_the_work_grid_is_not_deskewed(monkeypatch) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", 100)
    page = _page()
    edit = PageEdit(quarter_turns=2, deskew_tenths=50)
    assert np.array_equal(
        edited_page(page, edit).pixels, edited_page(page, replace(edit, deskew_tenths=None)).pixels
    )
