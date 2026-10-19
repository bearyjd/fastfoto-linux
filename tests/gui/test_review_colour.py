"""Per-page output choices preserve review edits and explain the actual PDF representation."""

from dataclasses import replace

import pytest

from fastfoto_linux.documents import ColourMode, ColourPolicy
from fastfoto_linux.documents.auto_colour import ColourDecision, ColourReason
from fastfoto_linux.gui.docform import DocumentForm, to_document_settings, validate_document_form
from fastfoto_linux.gui.review import ReviewState, review_items
from tests.gui.review_helpers import draft


def decided_draft(folder):
    source = draft(folder)
    decisions = (
        ColourDecision(ColourMode.COLOUR, ColourMode.GREY, ColourReason.FAINT_MARKS),
        ColourDecision(ColourMode.COLOUR, ColourMode.BW, ColourReason.BILEVEL),
        ColourDecision(ColourMode.COLOUR, ColourMode.COLOUR, ColourReason.COLOUR_MARKS),
    )
    return replace(
        source,
        pages=tuple(
            replace(page, colour=decision)
            for page, decision in zip(source.pages, decisions, strict=True)
        ),
    )


def test_auto_form_is_opt_in_and_reaches_document_settings(out):
    assert DocumentForm().colour == "colour"
    form = DocumentForm(colour="auto", searchable=False)
    assert validate_document_form(form) == {}
    assert to_document_settings(form, out, ocr_available=False).colour is ColourPolicy.AUTO


def test_auto_rows_explain_actual_mode_and_include_dropped_pages(out):
    rows = review_items(ReviewState(decided_draft(out)), ColourPolicy.AUTO)
    assert [(row.colour_mode, row.colour_reason) for row in rows] == [
        ("grey", "faint_marks"),
        ("bw", "bilevel"),
        ("colour", "colour_marks"),
    ]
    assert rows[0].colour_policy == "auto"
    assert rows[0].colour_override == ""
    assert rows[0].colour_text == "Auto: Grey — faint marks"
    assert rows[1].dropped


def test_override_clear_and_explicit_auto_follow_raw_identity_through_other_edits(out):
    original = ReviewState(decided_draft(out))
    changed = original.set_colour(2, ColourPolicy.COLOUR)
    changed = changed.toggle(2).rotate(2, 1).move(2, 0).toggle_split(3).name_part(2, "Other")
    row = next(row for row in review_items(changed, ColourPolicy.AUTO) if row.number == 2)
    assert (row.colour_mode, row.colour_override, row.included, row.turns) == (
        "colour",
        "colour",
        True,
        1,
    )
    assert original.draft.edits == {}
    cleared = changed.set_colour(2, None)
    assert cleared.draft.edits[2].quarter_turns == 1
    assert cleared.draft.order == changed.draft.order
    assert cleared.draft.splits == changed.draft.splits
    assert cleared.draft.part_names == changed.draft.part_names
    assert review_items(cleared, ColourPolicy.AUTO)[0].colour_mode == "bw"
    explicit_auto = cleared.set_colour(2, ColourPolicy.AUTO)
    assert review_items(explicit_auto, ColourPolicy.COLOUR)[0].colour_mode == "bw"
    assert review_items(explicit_auto, ColourPolicy.COLOUR)[0].colour_override == "auto"


def test_explicit_choice_equal_to_document_policy_remains_an_override(out):
    state = ReviewState(decided_draft(out)).set_colour(1, ColourPolicy.GREY)
    assert review_items(state, ColourPolicy.GREY)[0].colour_override == "grey"
    assert review_items(state, ColourPolicy.COLOUR)[0].colour_mode == "grey"


@pytest.mark.parametrize("number,policy", [(0, ColourPolicy.AUTO), (99, None), (1, "sepia")])
def test_invalid_page_or_policy_cannot_change_review(out, number, policy):
    state = ReviewState(decided_draft(out))
    with pytest.raises(ValueError):
        state.set_colour(number, policy)
    assert not state.draft.edits


@pytest.mark.parametrize("source_kind", [ColourMode.GREY, ColourMode.BW])
def test_manual_colour_request_reports_actual_source_richness(out, source_kind):
    source = decided_draft(out)
    decision = ColourDecision(
        source_kind,
        source_kind,
        ColourReason.SOURCE_BW if source_kind is ColourMode.BW else ColourReason.CONTINUOUS_TONE,
    )
    source = replace(source, pages=(replace(source.pages[0], colour=decision),))
    state = ReviewState(source).set_colour(1, ColourPolicy.COLOUR)
    row = review_items(state, ColourPolicy.AUTO)[0]
    assert row.colour_policy == "colour"
    assert row.colour_mode == source_kind.value
    assert row.colour_override == "colour"
