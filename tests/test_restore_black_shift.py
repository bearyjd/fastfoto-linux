"""The black-point shift limit: how far balancing may move a channel's black point.

Aligning the channels' black points can move one a long way. The limit holds it to what the cast
measured at the neutrals supports, so a print whose shadows are tinted much more than its
neutrals are does not get the shadow tint swapped for a different one.
"""

import numpy as np
import pytest

from fastfoto_linux.enhance.restore import _black_shift_limit, restore_colour
from tests._restore_synth import DPI, fade_between, make_cast_card

# The limit is max(12, 1.5 x evidence) levels: flat at 12 up to the knee (evidence 8), then
# 1.5 levels per unit of evidence. Literal numbers on purpose: they pin the constants.
KNEE_EVIDENCE = 8.0
FLOOR_LEVELS = 12.0

SHADOW_CAST_BLACK = (100.0, 20.0, 20.0)  # black levels: red far above green and blue
SHADOW_CAST_WHITE = (200.0, 230.0, 230.0)  # white levels: red is the narrowest channel
SCENE_CHROMA = 12.0
BLACK_PERCENTILE = 0.5
MIN_SPREAD_BEFORE = 60.0  # levels: sanity, the fixture's black points really are far apart
# Black-point spread left after restoring: ~1 if nothing limits the shift (or the limit is far
# too generous), ~62 if the limit ignores the evidence and stays at the 12-level floor.
MIN_SPREAD_KEPT = 6.0
MAX_SPREAD_KEPT = 30.0


@pytest.mark.parametrize("evidence", [0.0, 4.0, 7.9])
def test_below_the_knee_the_limit_is_the_floor(evidence: float) -> None:
    assert _black_shift_limit(evidence) == pytest.approx(FLOOR_LEVELS)


def test_at_the_knee_the_floor_and_the_proportional_limit_meet() -> None:
    assert _black_shift_limit(KNEE_EVIDENCE) == pytest.approx(FLOOR_LEVELS)


@pytest.mark.parametrize(
    ("evidence", "levels"),
    [(8.4, 12.6), (10.0, 15.0), (12.0, 18.0), (20.0, 30.0), (40.0, 60.0)],  # 10: the threshold
)
def test_above_the_knee_the_limit_grows_with_the_evidence(evidence: float, levels: float) -> None:
    assert _black_shift_limit(evidence) == pytest.approx(levels)


def _black_point_spread(img: np.ndarray) -> float:
    """Levels between the highest and the lowest channel black point (0.5th percentile)."""
    return float(np.ptp(np.percentile(img.reshape(-1, 3), BLACK_PERCENTILE, axis=0)))


def test_a_shadow_cast_beyond_what_the_neutrals_support_is_only_partly_removed() -> None:
    """Aligning these black points takes about 53 levels; the evidence supports about 44."""
    faded = fade_between(make_cast_card(SCENE_CHROMA), SHADOW_CAST_BLACK, SHADOW_CAST_WHITE)
    before = _black_point_spread(faded)
    after = _black_point_spread(restore_colour(faded, DPI))
    assert before >= MIN_SPREAD_BEFORE
    assert MIN_SPREAD_KEPT <= after <= MAX_SPREAD_KEPT  # balanced, but not fully aligned
