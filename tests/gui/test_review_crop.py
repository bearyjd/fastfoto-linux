"""The review state, rows and side keep a hand crop; only the previewed page refreshes."""

from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.page_crop import CROP_UNITS, PageCrop
from fastfoto_linux.gui import reviewcrop
from fastfoto_linux.gui.review import ReviewState, review_items
from fastfoto_linux.gui.reviewjobs import PreviewCompletion, PreviewMeta
from fastfoto_linux.gui.reviewside import PAGE_AFFECTING
from tests.gui.review_helpers import draft
from tests.gui.test_reviewside import opened

CROP = PageCrop(1000, 1000, 9000, 9000)
DRAG = {
    "painted_width": 500.0,
    "painted_height": 1000.0,
    "item_width": 600.0,
    "item_height": 1200.0,
}


def test_set_crop_is_kept_and_cleared_without_touching_the_input(out):
    state = ReviewState(draft(out))
    cropped = state.set_crop(2, CROP)
    assert cropped.draft.edits[2].crop == CROP
    assert state.draft.edits == {}
    assert cropped.set_crop(2, None).draft.edits == {}


def test_rows_say_cropped_by_hand_only_for_a_cropped_page(out):
    rows = review_items(ReviewState(draft(out)).set_crop(2, CROP))
    assert [(row.cropped, row.crop_text) for row in rows] == [
        (False, ""),
        (True, "Cropped by hand"),
        (False, ""),
    ]
    assert not review_items(ReviewState(draft(out)).set_crop(2, CROP).set_crop(2, None))[1].cropped


def test_a_crop_does_not_change_which_pages_stay(out):
    base = ReviewState(draft(out))
    assert base.set_crop(1, CROP).draft.kept == base.draft.kept


def test_set_crop_is_an_operation_that_can_change_page_pixels():
    assert "set_crop" in PAGE_AFFECTING


def test_a_crop_on_the_previewed_page_refreshes_the_output_preview(out):
    side, page = opened(out)
    calls = []
    page.worker.preview_page = lambda *args: calls.append(args)
    side.preview(1, "output")
    side.preview_ready(
        PreviewCompletion(calls[-1][0], out / "previews" / "page-0001-output-colour-off-r0.jpg")
    )
    before = len(calls)
    side.edit("set_crop", 2, CROP)
    assert len(calls) == before and side.preview_path is not None
    side.edit("set_crop", 1, CROP)
    assert len(calls) == before + 1 and side.preview_path is None
    assert calls[-1][0].draft.edits[1].crop == CROP


def test_the_source_size_and_dpi_come_with_the_source_preview(out):
    side, page = opened(out)
    calls = []
    page.worker.preview_page = lambda *args: calls.append(args)
    side.preview(1)
    request = side._preview_requested
    path = out / "previews" / "page-0001.jpg"
    side.preview_ready(PreviewCompletion(request, path, size=(1200, 1800), dpi=300))
    assert (side.preview_size, side.preview_dpi) == ((1200, 1800), 300)
    side.preview(2)
    assert side.preview_size is None and side.preview_dpi is None


def test_a_legacy_tuple_answer_may_carry_a_named_measure(out):
    side, page = opened(out)
    page.worker.preview_page = lambda *args: None
    side.preview(1)
    path = out / "previews" / "page-0001.jpg"
    side.preview_ready((side.state.draft, 1, path, "", PreviewMeta(1200, 1800, 300)))
    assert (side.preview_size, side.preview_dpi) == ((1200, 1800), 300)


def test_anything_else_in_the_fifth_place_is_not_a_measure(out):
    side, page = opened(out)
    page.worker.preview_page = lambda *args: None
    side.preview(1)
    path = out / "previews" / "page-0001.jpg"
    side.preview_ready((side.state.draft, 1, path, "", (1200, 1800, 300)))
    assert (side.preview_size, side.preview_dpi) == (None, None)


def test_an_error_can_be_reported_through_the_side(out):
    side, page = opened(out)
    side.report_error("Nope.")
    assert page.controller._banner.kind == "error" and page.controller._banner.text == "Nope."


def test_the_cropped_output_names_are_accepted_for_their_own_page_only(out):
    side, page = opened(out)
    page.worker.preview_page = lambda *args: None
    side.preview(1, "output")
    request = side._preview_requested
    good = out / "previews" / "page-0001-output-grey-off-r0-c0123456789ab.jpg"
    other = out / "previews" / "page-0002-output-grey-off-r0-c0123456789ab.jpg"
    side.preview_ready(PreviewCompletion(request, other))
    assert side.preview_path is None
    side.preview_ready(PreviewCompletion(request, good))
    assert side.preview_path == good


def drag(side, number=1, **override):
    values = {"x0": 100, "y0": 200, "x1": 500, "y1": 1000, **DRAG, **override}
    return reviewcrop.crop_from_drag(side, number, **values)


def sourced(out):
    side, page = opened(out)
    page.worker.preview_page = lambda *args: None
    side.preview(1)
    side.preview_ready(
        PreviewCompletion(
            side._preview_requested,
            out / "previews" / "page-0001.jpg",
            size=(1000, 2000),
            dpi=254,
        )
    )
    return side


def test_a_drag_on_the_source_preview_sets_the_crop(out):
    side = sourced(out)
    assert drag(side) is True
    assert side.state.draft.edits[1].crop == CROP


def test_a_drag_under_five_millimetres_is_refused_and_changes_nothing(out):
    side = sourced(out)
    assert drag(side, x1=124) is False
    assert side.state.draft.edits.get(1, PageEdit()).crop is None


def test_a_drag_while_the_output_view_is_showing_is_refused(out):
    side = sourced(out)
    side.preview_view = "output"
    assert drag(side) is False
    assert reviewcrop.crop_rectangle(side) == []


def test_a_drag_without_a_source_preview_of_that_page_is_refused(out):
    side = sourced(out)
    assert drag(side, number=2) is False
    side2, _page = opened(out)
    assert drag(side2) is False


def test_the_crop_rectangle_is_the_pixel_box_in_the_source_frame(out):
    side = sourced(out)
    assert reviewcrop.crop_rectangle(side) == []
    drag(side)
    assert reviewcrop.crop_rectangle(side) == [100, 200, 900, 1800]


def test_clear_crop_removes_it(out):
    side = sourced(out)
    drag(side)
    assert reviewcrop.clear_crop(side, 1) is True
    assert side.state.draft.edits.get(1, PageEdit()).crop is None


def test_a_bad_crop_is_refused_with_no_numbers_in_the_message(out):
    side = sourced(out)
    assert reviewcrop.store_crop(side, 99, 0, 0, 5000, 5000) is False
    assert reviewcrop.store_crop(side, 1, 5000, 0, 5000, 5000) is False
    assert reviewcrop.store_crop(side, 1, 0, 0, CROP_UNITS + 1, 5000) is False
    assert reviewcrop.store_crop(side, 1, 0, 0, True, 5000) is False
    assert reviewcrop.store_crop(side, 1, 0, 0, 5000, 5000) is True
    assert side.state.draft.edits[1].crop == PageCrop(0, 0, 5000, 5000)
