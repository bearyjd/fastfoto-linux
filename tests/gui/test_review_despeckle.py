"""Remove specks in the review: the edit, the words, the refresh, and reopening."""

from dataclasses import replace

import pytest

from fastfoto_linux.documents import CleanupPolicy, ColourPolicy, DespeckleStatus, OcrMode
from fastfoto_linux.documents.draft_edit import DocumentEditError
from fastfoto_linux.gui import reviewside
from fastfoto_linux.gui.review import ReviewState, preview_despeckle_text, review_items
from fastfoto_linux.gui.reviewjobs import PreviewCompletion
from fastfoto_linux.gui.reviewside import ReviewSide
from tests.gui.test_controller_documents import Page
from tests.gui.test_review_cleanup import preview_calls, real_open, shown, synthetic_folder
from tests.gui.test_review_colour import decided_draft
from tests.gui.test_reviewside import opened

ON_TEXT = "Remove specks: on (document setting)"


def rows(state):
    return {row.number: row for row in review_items(state, ColourPolicy.AUTO)}


def test_the_switch_is_a_document_edit_that_defaults_to_off(out):
    state = ReviewState(decided_draft(out))
    assert state.draft.despeckle is False
    assert state.set_document_despeckle(True).draft.despeckle is True
    assert state.set_document_despeckle(True).set_document_despeckle(False).draft.despeckle is False
    assert state.draft.despeckle is False  # the original is not changed


def test_a_value_that_is_not_a_bool_is_refused(out):
    with pytest.raises(DocumentEditError):
        ReviewState(decided_draft(out)).set_document_despeckle("yes")


def test_only_a_black_and_white_page_says_so_and_only_when_the_switch_is_on(out):
    base = ReviewState(decided_draft(out))  # page 1 grey, page 2 black and white, page 3 colour
    assert [rows(base)[n].despeckle_text for n in (1, 2, 3)] == ["", "", ""]
    on = base.set_document_despeckle(True)
    assert rows(on)[2].despeckle_text == ON_TEXT
    assert rows(on)[1].despeckle_text == rows(on)[3].despeckle_text == ""
    assert rows(on.set_document_despeckle(False))[2].despeckle_text == ""


def test_a_page_override_to_grey_has_no_despeckle_text(out):
    state = ReviewState(decided_draft(out)).set_document_despeckle(True)
    state = state.set_colour(2, ColourPolicy.GREY)
    assert rows(state)[2].despeckle_text == ""


# -- the side ------------------------------------------------------------------------------------


def test_a_despeckle_edit_always_refreshes_an_open_output_preview(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output")
    shown(side, calls, out)
    side.edit("set_document_despeckle", True)
    assert len(calls) == 2
    assert calls[-1][0].draft.despeckle is True
    assert side.preview_path is None


def test_a_despeckle_edit_does_not_render_a_source_preview(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1)
    side.preview_ready((side.state.draft, 1, out / "previews" / "page-0001.jpg", ""))
    side.edit("set_document_despeckle", True)
    assert len(calls) == 1


def test_a_despeckle_edit_makes_the_review_dirty(out):
    side, _page = opened(out)
    side.dirty = False
    side.edit("set_document_despeckle", True)
    assert side.dirty is True


def test_the_preview_identity_is_the_draft_so_the_name_alone_tells_the_variant(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output")
    first = calls[-1][0]
    side.preview_ready(PreviewCompletion(first, out / "previews" / "page-0001-output-grey.jpg"))
    side.edit("set_document_despeckle", True)
    assert calls[-1][0] is not first and calls[-1][0].view == "output"
    assert calls[-1][0].cleaned is first.cleaned and calls[-1][0].crop == first.crop


def test_the_despeckled_names_are_accepted_as_previews(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output")
    request = calls[-1][0]
    for name in (
        "page-0001-output-bw-off-r0-s.jpg",
        "page-0001-output-bw-off-r2-s-crop.png",
        "page-0001-output-bw-off-r1-s-c0123456789ab.jpg",
    ):
        assert side._preview_path_valid(request, out / "previews" / name), name
    for name in ("page-0001-output-grey-off-r0-s.jpg", "page-0001-output-bw-off-r0-ss.jpg"):
        assert not side._preview_path_valid(request, out / "previews" / name), name


# -- reopening never gains despeckle -------------------------------------------------------------


def side_opening(folder):
    page = Page(folder)
    page.ready()
    side = ReviewSide(page.controller)
    page.controller.set_document_field("despeckle", True)
    seen = []
    page.worker.analyse_folder = lambda *args: seen.append(args)
    return side, page, seen


def test_open_folder_analyses_with_despeckle_off_whatever_the_form_says(out):
    side, page, seen = side_opening(out)
    side.open_folder(out)
    assert page.controller.document_form.despeckle is True  # the form itself is not changed
    assert seen[0][1].despeckle is False
    assert seen[0][1].cleanup is CleanupPolicy.OFF


def test_a_reopened_scan_really_comes_back_with_despeckle_off(out):
    side, _page, seen = side_opening(out)
    synthetic_folder(out)
    side.open_folder(out)
    assert real_open(out, replace(seen[0][1], ocr=OcrMode.OFF)).despeckle is False


def test_a_despeckle_edit_is_a_document_affecting_operation():
    assert "set_document_despeckle" in reviewside.DOCUMENT_AFFECTING


# -- the words about what the render did ---------------------------------------------------------


def test_only_the_applied_status_says_specks_were_removed():
    assert preview_despeckle_text(DespeckleStatus.APPLIED) == "specks removed"
    for status in set(DespeckleStatus) - {DespeckleStatus.APPLIED}:
        text = preview_despeckle_text(status)
        assert text.startswith("no specks removed"), status
        assert "specks removed" not in text.replace("no specks removed", "")


def test_the_abstain_reasons_are_named_and_an_unknown_result_is_not_claimed():
    assert preview_despeckle_text(DespeckleStatus.LOW_DPI) == (
        "no specks removed: resolution too low"
    )
    assert preview_despeckle_text(DespeckleStatus.NONE) == "no specks removed: nothing to remove"
    unknown = preview_despeckle_text(None)
    assert unknown == "specks requested (result unavailable)"


def test_the_side_keeps_the_status_of_the_shown_preview_and_clears_it(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output")
    path = out / "previews" / "page-0001-output-grey.jpg"
    side.preview_ready(PreviewCompletion(calls[-1][0], path, despeckle_status=DespeckleStatus.NONE))
    assert side.preview_despeckle_status is DespeckleStatus.NONE
    side.preview(2, "output")
    assert side.preview_despeckle_status is None
