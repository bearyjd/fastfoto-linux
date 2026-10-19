"""Auto must retain small colour and unsafe tones, without changing source pixels."""

from dataclasses import replace

import cv2
import numpy as np
import pytest

from fastfoto_linux.documents.auto_colour import (
    ColourDecision,
    ColourReason,
    classify_colour,
    resolve_colour,
)
from fastfoto_linux.documents.encode import encode_page, render_page
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy, output_mode
from tests.documents.auto_helpers import auto_page

C, G, B = ColourMode.COLOUR, ColourMode.GREY, ColourMode.BW


@pytest.mark.parametrize("dpi", [100, 300])
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("text", B),
        ("stamp", C),
        ("red_stroke", C),
        ("gradient", G),
        ("faint", G),
        ("reversed", G),
        ("sepia", C),
    ],
)
def test_auto_preserves_the_synthetic_acceptance_content(
    case: str, expected: ColourMode, dpi: int
) -> None:
    page = auto_page(case, dpi)
    original = page.pixels.copy()
    decision = classify_colour(page)
    assert decision.mode is expected
    assert decision.source_kind is C
    assert isinstance(decision.reason, ColourReason)
    assert classify_colour(page) == decision
    assert np.array_equal(page.pixels, original)


def test_neutral_scanner_noise_does_not_invent_colour() -> None:
    assert classify_colour(auto_page("neutral_noise")).mode in (G, B)


def test_neutral_grey_text_can_be_bilevel_without_fabricating_colour() -> None:
    source = auto_page()
    page = replace(source, pixels=source.pixels[:, :, 0].copy(), kind=G)
    decision = classify_colour(page)
    assert (decision.source_kind, decision.mode) == (G, B)


def test_native_bilevel_has_a_source_reason_and_retains_its_format() -> None:
    source = auto_page()
    page = replace(source, pixels=source.pixels[:, :, 0].copy(), kind=B)
    assert classify_colour(page) == ColourDecision(B, B, ColourReason.SOURCE_BW)


@pytest.mark.parametrize("kind", [C, G, B])
@pytest.mark.parametrize("requested", [C, G, B])
def test_existing_manual_mode_matrix_is_preserved(kind: ColourMode, requested: ColourMode) -> None:
    decision = ColourDecision(kind, B, ColourReason.BILEVEL)
    assert resolve_colour(decision, requested) is output_mode(kind, requested)
    assert resolve_colour(decision, ColourPolicy(requested.value)) is output_mode(kind, requested)


@pytest.mark.parametrize("chosen", [C, G, B])
def test_auto_uses_its_decision_instead_of_the_source_header(chosen: ColourMode) -> None:
    decision = ColourDecision(C, chosen, ColourReason.COLOUR_UNCERTAIN)
    assert resolve_colour(decision, ColourPolicy.AUTO) is chosen


def test_impossible_decision_cannot_claim_colour_from_a_grey_source() -> None:
    with pytest.raises(ValueError, match=r"source|rich|colour"):
        ColourDecision(G, C, ColourReason.COLOUR_MARKS)


@pytest.mark.parametrize("mode", [C, G, B])
def test_preview_render_uses_the_same_full_resolution_conversion_as_export(
    mode: ColourMode,
) -> None:
    source = auto_page("faint")
    original = source.pixels.copy()
    rendered = render_page(source, mode)
    decoded = cv2.imdecode(
        np.frombuffer(encode_page(source, mode).data, np.uint8), cv2.IMREAD_UNCHANGED
    )
    if mode is C:
        decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
    assert rendered.shape == decoded.shape
    assert np.abs(rendered.astype(int) - decoded.astype(int)).mean() < 3
    assert np.array_equal(source.pixels, original)


def test_bilevel_render_is_lossless_and_does_not_rethreshold_existing_one_bit_input() -> None:
    pixels = np.zeros((80, 70), np.uint8)
    pixels[15:65, 10:60] = 255
    page = LoadedPage(pixels, B, 100)
    assert np.array_equal(render_page(page, B), pixels)
