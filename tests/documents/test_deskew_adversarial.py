"""The estimate is never bolder than the one before the noise change, except by noise alone.

OLD holds the verdicts of the estimate as it was before the noise measurement changed
(computed once on that code and kept as literals) for the pages of deskew_adversarial:
light blocks and bands at the frame edge, ruled lines, a textured photo corner, marks and blocks on
noisy paper. Where it said anything but estimated (the turn would cut content, or it was
unsure) the estimate now must not say estimated, except the two cases of NOISE_ONLY: a flat
block 35 levels under the paper on paper with noise of 6 and 10 levels (about six and 3.5 sigma),
which the noise-aware floor deliberately reads as paper.
"""

import pytest

from fastfoto_linux.documents.deskew import SkewStatus, estimate_skew
from tests.documents.deskew_adversarial import CASES
from tests.documents.deskew_fixtures import loaded

OLD = {
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
    "noisyblock6_150": "would_clip",
    "noisyblock6_205": "would_clip",
    "noisyblock10_150": "would_clip",
    "noisyblock10_205": "would_clip",
}
NOISE_ONLY = {"noisyblock6_205", "noisyblock10_205"}


def test_the_recorded_cases_are_the_cases() -> None:
    assert OLD.keys() == CASES.keys()


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_estimate_is_never_bolder_than_before(name: str) -> None:
    pixels, dpi = CASES[name]()
    status = estimate_skew(loaded(pixels, dpi=dpi)).status
    if name in NOISE_ONLY:
        assert status is SkewStatus.ESTIMATED
    elif OLD[name] != SkewStatus.ESTIMATED.value:
        assert status is not SkewStatus.ESTIMATED
    else:
        assert status is SkewStatus.ESTIMATED
