"""Pins of the deskew estimate's safety margin: pages that try to make it accept a cut.

The verdicts are those of the estimate as of this change (computed once and kept as literals):
light blocks and bands at the frame edge, ruled lines, a textured photo corner, marks and
blocks on noisy paper, a small footer mark on paper with noise of 4 levels, and evenly lit paper
with noise of 6 levels, whose false ``would_clip`` is the documented fail-safe limit. A change
that makes the estimate bolder (a lower floor) flips a pinned ``would_clip`` to ``estimated``; one
that cures the false abstention must still keep every other pin.
"""

import pytest

from fastfoto_linux.documents.deskew import estimate_skew
from tests.documents.deskew_adversarial import CASES
from tests.documents.deskew_fixtures import loaded

PINNED = {
    "block60_140": "would_clip",
    "block60_180": "would_clip",
    "block60_205": "would_clip",
    "block60_225": "would_clip",
    "block200_140": "would_clip",
    "block200_180": "would_clip",
    "block200_205": "would_clip",
    "block200_225": "would_clip",
    "block400_140": "would_clip",
    "block400_180": "would_clip",
    "block400_205": "would_clip",
    "block400_225": "would_clip",
    "band40_190": "would_clip",
    "band40_205": "would_clip",
    "band40_225": "would_clip",
    "band150_190": "would_clip",
    "band150_205": "would_clip",
    "band150_225": "would_clip",
    "band300_190": "would_clip",
    "band300_205": "would_clip",
    "band300_225": "would_clip",
    "line_150": "would_clip",
    "line_200": "would_clip",
    "line_225": "would_clip",
    "texture100": "would_clip",
    "texture300": "would_clip",
    "mark6_190": "would_clip",
    "mark6_150": "would_clip",
    "mark10_190": "estimated",
    "mark10_150": "would_clip",
    "vigblock0_150": "would_clip",
    "vigblock0_195": "would_clip",
    "vigblock0_205": "estimated",
    "vigblock3_150": "would_clip",
    "vigblock3_195": "would_clip",
    "vigblock3_205": "estimated",
    "footer4_215": "would_clip",
    "evenly_lit6": "would_clip",
    "noisyblock6_150": "would_clip",
    "noisyblock6_205": "would_clip",
    "noisyblock10_150": "would_clip",
    "noisyblock10_205": "would_clip",
}


def test_the_pinned_cases_are_the_cases() -> None:
    assert PINNED.keys() == CASES.keys()


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_verdict_is_the_pinned_one(name: str) -> None:
    pixels, dpi = CASES[name]()
    assert estimate_skew(loaded(pixels, dpi=dpi)).status.value == PINNED[name]
