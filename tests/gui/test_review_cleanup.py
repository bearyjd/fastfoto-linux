"""Paper cleanup in the review: edits (a document review keeps no undo history), the words,
the preview identity, reopening."""

import json
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image

from fastfoto_linux.documents import CleanupPolicy, ColourPolicy, DocumentSettings, OcrMode
from fastfoto_linux.documents.cleanup import CleanupStatus
from fastfoto_linux.documents.draft_store import REVIEW_FILE, save_draft
from fastfoto_linux.gui.review import ReviewState, review_items
from fastfoto_linux.gui.reviewjobs import PreviewCompletion, ReviewJobs
from fastfoto_linux.gui.reviewside import ReviewSide
from fastfoto_linux.gui.state import State
from tests.gui.doc_helpers import DocRecordingSink
from tests.gui.review_helpers import draft
from tests.gui.test_controller_documents import Page
from tests.gui.test_review_colour import decided_draft
from tests.gui.test_reviewside import opened

LIGHT, STRONG, OFF = CleanupPolicy.LIGHT, CleanupPolicy.STRONG, CleanupPolicy.OFF


def rows(state):
    return {row.number: row for row in review_items(state, ColourPolicy.AUTO)}


def test_items_say_where_the_level_comes_from(out):
    base = ReviewState(decided_draft(out))
    assert rows(base)[1].cleanup_text == "Paper cleanup: off"
    assert rows(base)[1].cleanup_override == ""
    document = base.set_document_cleanup(LIGHT)
    assert rows(document)[1].cleanup_text == "Paper cleanup: Light requested (document setting)"
    page = document.set_cleanup(1, STRONG)
    assert rows(page)[1].cleanup_text == "Paper cleanup: Strong requested (this page)"
    assert rows(page)[1].cleanup_override == "strong"
    assert rows(page)[3].cleanup_override == ""


def test_black_and_white_pages_say_the_cleanup_is_not_used(out):
    state = ReviewState(decided_draft(out)).set_document_cleanup(STRONG)
    assert rows(state)[2].cleanup_text == "Paper cleanup: not used for black and white output"


def test_a_page_override_of_off_beats_the_document_level(out):
    state = ReviewState(decided_draft(out)).set_document_cleanup(STRONG).set_cleanup(1, OFF)
    assert rows(state)[1].cleanup_text == "Paper cleanup: off"
    assert rows(state)[1].cleanup_override == "off"
    assert rows(state)[3].cleanup_text == "Paper cleanup: Strong requested (document setting)"


def test_edits_are_pure_and_clearing_restores_the_document_level(out):
    original = ReviewState(decided_draft(out))
    changed = original.set_document_cleanup(LIGHT).set_cleanup(1, STRONG)
    assert original.draft.cleanup is OFF and original.draft.edits == {}
    assert changed.draft.cleanup is LIGHT
    cleared = changed.set_cleanup(1, None)
    assert rows(cleared)[1].cleanup_text == "Paper cleanup: Light requested (document setting)"
    assert cleared.draft.edits.get(1) is None or cleared.draft.edits[1].cleanup is None


@pytest.mark.parametrize("bad", [(0, LIGHT), (99, None), (1, "medium")])
def test_a_bad_page_or_level_cannot_change_the_review(out, bad):
    state = ReviewState(decided_draft(out))
    with pytest.raises(ValueError):
        state.set_cleanup(*bad)
    with pytest.raises(ValueError):
        state.set_document_cleanup("medium")


# --- the side: preview refresh, identity -----------------------------------------------------


def shown(side, calls, out):
    path = out / "previews" / "page-0001-output-grey.jpg"
    side.preview_ready(PreviewCompletion(calls[-1][0], path))


def preview_calls(side, page):
    calls = []
    page.worker.preview_page = lambda *args: calls.append(args)
    return calls


def test_a_cleanup_edit_of_the_previewed_page_refreshes_the_output_preview(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output")
    shown(side, calls, out)
    side.edit("set_cleanup", 1, LIGHT)
    assert len(calls) == 2 and calls[-1][0].draft is side.state.draft
    assert side.preview_path is None


def test_a_cleanup_edit_of_another_page_leaves_the_preview_alone(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output")
    output = out / "previews" / "page-0001-output-grey.jpg"
    side.preview_ready(PreviewCompletion(calls[-1][0], output))
    side.edit("set_cleanup", 2, LIGHT)
    assert side.preview_path == output and len(calls) == 1


def test_a_document_cleanup_edit_always_refreshes_an_open_output_preview(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output")
    shown(side, calls, out)
    side.edit("set_document_cleanup", STRONG)
    assert len(calls) == 2
    assert calls[-1][0].draft.cleanup is STRONG
    assert side.preview_path is None


def test_a_document_cleanup_edit_does_not_render_a_source_preview(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1)
    side.preview_ready((side.state.draft, 1, out / "previews" / "page-0001.jpg", ""))
    side.edit("set_document_cleanup", STRONG)
    assert len(calls) == 1


def test_the_preview_identity_includes_cleaned_and_crop(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    output = out / "previews" / "page-0001-output-grey.jpg"
    side.preview(1, "output")
    first = calls[-1][0]
    assert first.cleaned is True and first.crop is None
    side.preview_ready(PreviewCompletion(first, output))
    assert side.preview(1, "output") == output.as_uri()  # the same request is the cached one
    assert len(calls) == 1
    assert side.preview(1, "output", cleaned=False) == ""
    assert len(calls) == 2 and calls[-1][0].cleaned is False
    cleaned_off = calls[-1][0]
    side.preview_ready(PreviewCompletion(cleaned_off, output))
    assert side.preview(1, "output", cleaned=False) == output.as_uri()
    assert side.preview(1, "output", cleaned=True) == ""  # the other side of the toggle is not it
    assert len(calls) == 3
    assert side.preview(1, "output", cleaned=True, crop=(500, 500)) == ""
    assert calls[-1][0].crop == (500, 500)
    assert len(calls) == 4


def test_a_late_answer_for_the_other_side_of_the_toggle_is_ignored(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    output = out / "previews" / "page-0001-output-grey.jpg"
    side.preview(1, "output", cleaned=True)
    cleaned = calls[-1][0]
    side.preview(1, "output", cleaned=False)
    side.preview_ready(PreviewCompletion(cleaned, output))
    assert side.preview_path is None
    assert side.preview_cleaned is False


def test_cleanup_status_is_cached_then_cleared_and_stale_results_are_ignored(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output")
    first = calls[-1][0]
    path = out / "previews" / "page-0001-output-grey-off-r0.jpg"
    side.preview_ready(PreviewCompletion(first, path, cleanup_status=CleanupStatus.DARK))
    assert side.preview_cleanup_status is CleanupStatus.DARK
    assert side.preview(1, "output") == path.as_uri()
    assert side.preview_cleanup_status is CleanupStatus.DARK
    side.preview(2, "output")
    assert side.preview_cleanup_status is None
    side.preview_ready(PreviewCompletion(first, path, cleanup_status=CleanupStatus.STOCK))
    assert side.preview_cleanup_status is None
    assert side.preview_path is None


def test_an_edit_refresh_keeps_cleaned_and_crop(out):
    side, page = opened(out)
    calls = preview_calls(side, page)
    side.preview(1, "output", cleaned=False, crop=(100, 900))
    shown(side, calls, out)
    side.edit("rotate", 1, 1)
    request = calls[-1][0]
    assert (request.cleaned, request.crop) == (False, (100, 900))
    assert (side.preview_cleaned, side.preview_crop) == (False, (100, 900))


def test_the_source_view_forces_cleaned_and_no_crop(out):
    side, page = opened(out)
    preview_calls(side, page)
    side.preview(1, "output", cleaned=False, crop=(1, 2))
    side.preview(1, "source", cleaned=False, crop=(1, 2))
    assert (side.preview_cleaned, side.preview_crop) == (True, None)
    assert side.preview_view == "source"


# --- reopening never gains cleanup -------------------------------------------------------------


def synthetic_folder(folder):
    for n in range(1, 4):
        path = folder / f"page-{n:04d}.png"
        Image.new("RGB", (600, 800), "white").save(path, dpi=(300, 300))
    return folder


def real_open(folder, settings, *, jobs_sink=None):
    """Run the analysis job exactly as the worker would for the settings the side passed."""
    sink = jobs_sink or DocRecordingSink()
    tasks = []
    tools = SimpleNamespace(open_review=None, write_review=None, preview_review=None)
    ReviewJobs(sink, tasks.append, tools).analyse_folder(folder, settings)
    tasks[0](threading.Event())()
    result = sink.value("finished")
    assert result.error is None, result.error
    return result.draft


def side_opening(folder, form_cleanup="strong"):
    page = Page(folder)
    page.ready()
    side = ReviewSide(page.controller)
    page.controller.set_document_field("cleanup", form_cleanup)
    seen = []
    page.worker.analyse_folder = lambda *args: seen.append(args)
    return side, page, seen


def test_open_folder_forces_cleanup_off_whatever_the_form_says(out):
    side, page, seen = side_opening(out)
    side.open_folder(out)
    assert page.controller.document_form.cleanup == "strong"
    assert seen[0][1].cleanup is OFF
    assert page.controller.state is State.PROCESSING


def test_reopen_forces_cleanup_off_too(out):
    side, _page, seen = side_opening(out)
    side._saved = replace(draft(out), raw_dir=out)
    side.reopen()
    assert seen[0][1].cleanup is OFF


@pytest.mark.parametrize("sidecar", ["missing", "v2", "v1"])
def test_an_old_or_missing_sidecar_never_gains_cleanup(out, sidecar):
    folder = synthetic_folder(out)
    settings = DocumentSettings(output_root=out, ocr=OcrMode.OFF, cleanup=STRONG)
    if sidecar != "missing":
        analysed = real_open(folder, replace(settings, cleanup=OFF))
        save_draft(analysed, replace(settings, cleanup=OFF))
        path = folder / REVIEW_FILE
        data = json.loads(path.read_bytes())
        assert data["version"] == 2
        if sidecar == "v1":
            data["version"] = 1
            for entry in data["pages"]:
                entry.pop("colour", None)
            for edit in data.get("edits", {}).values():
                edit["colour"] = None
            data.pop("options", None)
        path.write_text(json.dumps(data))
    side, _page, seen = side_opening(folder)
    side.open_folder(folder)
    opened_settings = seen[0][1]
    assert opened_settings.cleanup is OFF
    # The form asks for searchable text, which CI cannot provide; cleanup is what is under test.
    opened_draft = real_open(folder, replace(opened_settings, ocr=OcrMode.OFF))
    assert opened_draft.cleanup is OFF
    assert all(edit.cleanup is None for edit in opened_draft.edits.values())
    # The unguarded settings would have leaked the form's level: this is what the guard prevents.
    assert real_open(folder, settings).cleanup is (STRONG if sidecar == "missing" else OFF)


def test_a_v3_sidecar_keeps_its_own_cleanup_on_reopen(out):
    folder = synthetic_folder(out)
    settings = DocumentSettings(output_root=out, ocr=OcrMode.OFF)
    analysed = real_open(folder, settings)
    save_draft(replace(analysed, cleanup=LIGHT), settings)
    side, _page, seen = side_opening(folder)
    side.open_folder(folder)
    assert real_open(folder, replace(seen[0][1], ocr=OcrMode.OFF)).cleanup is LIGHT


def test_a_fresh_scan_still_takes_the_forms_level(out):
    side, _page, _seen = side_opening(out, "light")
    assert side._current_settings().cleanup is LIGHT


# -- the panel names the result of the page that was previewed ------------------------------------


def known_rows(state, known):
    return {row.number: row for row in review_items(state, ColourPolicy.AUTO, known)}


def test_a_known_skip_is_added_to_the_previewed_pages_words(out):
    state = ReviewState(decided_draft(out)).set_document_cleanup(LIGHT)
    text = known_rows(state, {1: CleanupStatus.DARK})[1].cleanup_text
    assert text == "Paper cleanup: Light requested (document setting) — skipped: paper too dark"
    assert "skipped" in text


def test_a_known_applied_result_is_added_too(out):
    state = ReviewState(decided_draft(out)).set_document_cleanup(LIGHT)
    text = known_rows(state, {1: CleanupStatus.APPLIED})[1].cleanup_text
    assert text == "Paper cleanup: Light requested (document setting) — applied"


def test_without_a_known_result_or_for_another_page_the_words_are_unchanged(out):
    state = ReviewState(decided_draft(out)).set_document_cleanup(LIGHT)
    plain = rows(state)
    assert known_rows(state, {})[1].cleanup_text == plain[1].cleanup_text
    assert known_rows(state, None)[1].cleanup_text == plain[1].cleanup_text
    other = known_rows(state, {3: CleanupStatus.DARK})
    assert other[1].cleanup_text == plain[1].cleanup_text
    assert "—" not in other[1].cleanup_text


def test_off_and_black_and_white_pages_never_gain_a_result(out):
    state = ReviewState(decided_draft(out)).set_document_cleanup(STRONG).set_cleanup(1, OFF)
    got = known_rows(state, {1: CleanupStatus.DARK, 2: CleanupStatus.BW})
    assert got[1].cleanup_text == "Paper cleanup: off"
    assert got[2].cleanup_text == "Paper cleanup: not used for black and white output"
