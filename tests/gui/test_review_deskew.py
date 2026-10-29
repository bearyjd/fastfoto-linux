"""Straighten and Undo straighten in the review: the job, the stale drop, the sentences."""

import threading
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.documents.deskew import SkewStatus, estimate_skew
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_store import open_draft
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.gui.review import ReviewState, review_items
from fastfoto_linux.gui.reviewdeskew import SENTENCES
from fastfoto_linux.gui.reviewjobs import DESKEW_ERROR, DeskewAnswer, PreviewCompletion, ReviewJobs
from fastfoto_linux.gui.state import ActionBlockedError, State
from fastfoto_linux.session.raw import list_pages
from tests.documents.deskew_fixtures import skewed, text_page
from tests.gui.test_reviewside import opened

HALF = PageCrop(5000, 0, 10_000, 10_000)
ESTIMATED = SkewStatus.ESTIMATED


def answer(side, number=1, status=ESTIMATED, tenths=41):
    return DeskewAnswer(side.state.draft, number, status, tenths)


def started(out):
    """A review of three pages with a fake worker that records the estimates it was asked for."""
    side, page = opened(out)
    calls = []
    page.worker.estimate_page = lambda *args: calls.append(args)
    return side, page, calls


def edit_of(side, number=1):
    return side.state.draft.edits.get(number, PageEdit())


# -- the sentences -----------------------------------------------------------------------------


def test_every_status_but_estimated_has_a_sentence_and_so_has_an_error():
    assert set(SENTENCES) == (set(SkewStatus) - {ESTIMATED}) | {DESKEW_ERROR}
    assert all(text.endswith(".") and "/" not in text for text in SENTENCES.values())
    assert SENTENCES[SkewStatus.LEVEL] == "This page is already straight (tilted less than 0.3°)."
    assert SENTENCES[DESKEW_ERROR] == "Could not measure this page's tilt."
    assert SENTENCES[SkewStatus.CROPPED] == SENTENCES[SkewStatus.UNSURE]


# -- the action ------------------------------------------------------------------------------


def test_straighten_asks_the_worker_for_the_focused_page(out):
    side, _page, calls = started(out)
    before = side.state.draft
    side.deskew.straighten(1)
    assert calls == [(before, 1)]
    assert side.deskew.pending == (before, 1) and not side.deskew.can_straighten


def test_estimated_applies_the_angle_and_clears_the_crop(out):
    side, _page, _calls = started(out)
    side.edit("set_crop", 1, HALF)
    side.deskew.straighten(1)
    side.dirty = False
    side.deskew.ready(answer(side))
    assert edit_of(side).deskew_tenths == 41 and edit_of(side).crop is None
    assert side.dirty and side.deskew.pending is None
    assert side.deskew.message_text(1) == ""


def test_undo_clears_the_angle_and_the_crop_stays_gone(out):
    side, _page, _calls = started(out)
    side.edit("set_crop", 1, HALF)
    side.deskew.straighten(1)
    side.deskew.ready(answer(side))
    side.deskew.clear(1)
    assert edit_of(side).deskew_tenths is None and edit_of(side).crop is None
    assert side.deskew.can_straighten


@pytest.mark.parametrize("status", [*sorted(set(SkewStatus) - {ESTIMATED}), DESKEW_ERROR], ids=str)
def test_an_abstention_shows_its_sentence_and_leaves_the_draft_alone(out, status):
    side, _page, _calls = started(out)
    side.deskew.straighten(1)
    before = side.state.draft
    side.deskew.ready(answer(side, status=status, tenths=0))
    assert side.state.draft is before
    assert side.deskew.message_text(1) == SENTENCES[status]
    assert side.deskew.pending is None and side.deskew.can_straighten


def test_the_message_goes_when_the_page_changes_or_the_draft_is_edited(out):
    side, _page, _calls = started(out)
    side.deskew.straighten(1)
    side.deskew.ready(answer(side, status=SkewStatus.LEVEL, tenths=0))
    assert side.deskew.message_text(1) and side.deskew.message_text(2) == ""
    side.edit("focused", 2)
    assert side.deskew.message_text(2) == "" and side.deskew.message_text(1) == ""
    side.edit("focused", 1)
    side.edit("toggle", 3)
    assert side.deskew.message_text(1) == ""


# -- stale answers -----------------------------------------------------------------------------


def test_an_answer_for_another_focused_page_is_dropped(out):
    side, _page, _calls = started(out)
    side.deskew.straighten(1)
    side.edit("focused", 2)
    before = side.state.draft
    side.deskew.ready(DeskewAnswer(before, 1, ESTIMATED, 41))
    assert side.state.draft is before and side.deskew.pending is None
    assert side.deskew.message_text(1) == "" and side.deskew.message_text(2) == ""


def test_an_answer_for_an_edited_draft_is_dropped(out):
    side, _page, _calls = started(out)
    side.deskew.straighten(1)
    old = side.state.draft
    side.edit("toggle", 3)
    edited = side.state.draft
    side.deskew.ready(DeskewAnswer(old, 1, ESTIMATED, 41))
    assert side.state.draft is edited and edited.edits.get(1) is None
    side.deskew.ready(DeskewAnswer(old, 1, SkewStatus.LEVEL, 0))
    assert side.deskew.message_text(1) == ""


def test_an_answer_after_the_review_closed_is_dropped(out):
    side, _page, _calls = started(out)
    side.deskew.straighten(1)
    old = side.state.draft
    side.state = None
    side.deskew.ready(DeskewAnswer(old, 1, ESTIMATED, 41))
    assert side.deskew.pending is None and side.state is None


# -- who may ask -------------------------------------------------------------------------------


def test_can_straighten_is_false_while_busy_pending_or_straightened(out):
    side, page, calls = started(out)
    assert side.deskew.can_straighten
    page.worker.busy = True
    assert not side.deskew.can_straighten
    with pytest.raises(ActionBlockedError):
        side.deskew.straighten(1)
    page.worker.busy = False
    side.deskew.straighten(1)
    with pytest.raises(ActionBlockedError):
        side.deskew.straighten(1)
    assert len(calls) == 1
    side.deskew.ready(answer(side))
    assert edit_of(side).deskew_tenths == 41 and not side.deskew.can_straighten
    with pytest.raises(ActionBlockedError):
        side.deskew.straighten(1)


def test_straighten_refuses_a_page_that_is_not_the_focused_one_or_without_a_review(out):
    side, _page, calls = started(out)
    with pytest.raises(ActionBlockedError):
        side.deskew.straighten(2)
    side.state = None
    assert not side.deskew.can_straighten
    with pytest.raises(ActionBlockedError):
        side.deskew.straighten(1)
    assert calls == []


# -- the preview queue -------------------------------------------------------------------------


@pytest.mark.parametrize("status", [ESTIMATED, SkewStatus.LEVEL])
def test_a_preview_requested_during_the_job_is_dispatched_when_it_ends(out, status):
    side, page, _calls = started(out)
    previews = []
    page.worker.preview_page = lambda *args: previews.append(args)
    side.deskew.straighten(1)
    page.worker.busy = True
    side.preview(1, "source")
    assert previews == []
    page.worker.busy = False
    side.deskew.ready(answer(side, status=status, tenths=41 if status is ESTIMATED else 0))
    assert len(previews) == 1 and previews[0][1] == 1


def test_a_deskew_edit_of_the_previewed_page_refreshes_the_source_preview(out):
    side, page, _calls = started(out)
    previews = []
    page.worker.preview_page = lambda *args: previews.append(args)
    side.preview(1, "source")
    shown = out / "previews" / "page-0001.jpg"
    side.preview_ready(PreviewCompletion(side._preview_running, shown))
    assert side.preview_path == shown and len(previews) == 1
    side.edit("set_deskew", 2, 41)
    assert len(previews) == 1 and side.preview_path == shown
    side.edit("set_deskew", 1, 41)
    assert len(previews) == 2 and previews[-1][0] is side.state.draft
    assert side.preview_path is None


def test_the_straight_source_preview_is_accepted_and_a_wrong_one_is_not(out):
    side, page, _calls = started(out)
    page.worker.preview_page = lambda *args: None
    side.edit("set_deskew", 1, 41)
    side.preview(1, "source")
    good = out / "previews" / "page-0001-straight-p041.jpg"
    side.preview_ready(PreviewCompletion(side._preview_running, good))
    assert side.preview_path == good
    side.edit("set_deskew", 1, -7)
    side.preview(1, "source")
    side.preview_ready(
        PreviewCompletion(side._preview_running, out / "previews" / "page-0002-straight-p041.jpg")
    )
    assert side.preview_path is None


# -- the words ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tenths", "text"),
    [
        (41, "Straightened by 4.1°"),
        (-41, "Straightened by 4.1°"),
        (5, "Straightened by 0.5°"),
        (100, "Straightened by 10.0°"),
        (None, ""),
    ],
)
def test_the_page_says_how_far_it_was_straightened(out, tenths, text):
    side, _page, _calls = started(out)
    side.edit("set_deskew", 1, tenths)
    rows = {row.number: row for row in review_items(side.state)}
    assert rows[1].deskew_text == text and rows[2].deskew_text == ""


# -- the real pipeline -------------------------------------------------------------------------


def test_straightening_a_real_skewed_page_applies_the_measured_angle(out):
    rng = np.random.default_rng(7)
    page_pixels = skewed(text_page(rng), 41)
    raw = out / "raw"
    raw.mkdir()
    Image.fromarray(page_pixels).save(raw / "page-0001.png", dpi=(300, 300))
    settings = DocumentSettings(output_root=out, ocr=OcrMode.OFF)
    opened_draft = open_draft(raw, list_pages(raw), settings, fresh=True)
    side, page = opened(out)
    side.state = ReviewState(opened_draft)
    tasks, previews = [], []
    sink = SimpleNamespace(on_review_deskew=side.deskew.ready)
    tools = SimpleNamespace(
        open_review=None, write_review=None, preview_review=None, estimate_review=None
    )
    jobs = ReviewJobs(sink, tasks.append, tools)
    page.worker.estimate_page = jobs.estimate_page
    page.worker.preview_page = lambda *args: previews.append(args)
    page_record = opened_draft.pages[0]
    trimmed = page_record.trim.apply(load_page(raw / page_record.name, fallback_dpi=300))
    found = estimate_skew(trimmed)
    assert found.status is ESTIMATED
    side.deskew.straighten(1)
    tasks[0](threading.Event())()
    tenths = side.state.draft.edits[1].deskew_tenths
    assert tenths is not None and abs(tenths - found.tenths) <= 1
    assert side.deskew.pending is None
    side.preview(1, "source")
    assert previews and previews[-1][0].edits[1].deskew_tenths == tenths
    assert State.REVIEWING is page.controller.state
