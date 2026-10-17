"""What the README, the design note and the docstrings say about the backing band is what the
code does: the numbers are the constants of the code, the limits are the tested limits, and none
of it tells how the rule came about (that is in the pull request).
"""

import re
from pathlib import Path

import pytest

from fastfoto_linux.documents import band, guard, trim
from fastfoto_linux.documents.band import (
    BAND_SHARE,
    BOTTOM_EDGE,
    COLOURED_SHARE,
    FRINGE_PX,
    HOLE_MM,
    SHADOW_TOLERANCE,
    SHADOW_ZONE_MM,
    TOP_EDGE,
    WHITE_MIN,
)
from fastfoto_linux.documents.guard import (
    DUST_MM,
    DUST_TOLERANCE,
    SHADOW_BLUE_MAX,
    SHADOW_CLUSTER_MM,
    SHADOW_STRIP_MM,
)
from fastfoto_linux.documents.trim import MIN_PAPER_MM, TAIL_KEEP_MM
from fastfoto_linux.pipeline.crop import BACKGROUND_PRIOR_TOLERANCE

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
    "band docstring": band.__doc__ or "",
}
# Each fact is a number of the code with its unit and one word of context.
FACTS = {
    "size at the bottom": f"{BOTTOM_EDGE.min_mm:g} to {BOTTOM_EDGE.max_mm:g} mm",
    "size at the top": f"to {TOP_EDGE.max_mm:g} mm at the top",
    "reach": f"within {BOTTOM_EDGE.reach_mm:g} mm",
    "least that stays": f"at least {BOTTOM_EDGE.keep_mm:g} mm of the band stays",
    "most that stays": f"~{SHADOW_ZONE_MM:g} mm",
    "non-white share": f"{COLOURED_SHARE:.0%} of its width",
    "backing share": f"{BAND_SHARE:.0%} of those",
    "white": f"{WHITE_MIN} or more",
    "slip in a row": f"more than {HOLE_MM:g} mm of white",
    "page that stays": f"{MIN_PAPER_MM:g} mm of page",
    "fringe": f"within {FRINGE_PX} px",
    "strict tolerance": f"within {BACKGROUND_PRIOR_TOLERANCE:g} of the backing",
    "wide tolerance": f"within {SHADOW_TOLERANCE} of the backing",
    "shadow strip": f"{SHADOW_STRIP_MM:g} mm of the strip",
    "shadow speck": f"under {SHADOW_CLUSTER_MM:g} mm",
    "shadow hue": f"bluer than red by at most {SHADOW_BLUE_MAX}",
    "dust size": f"under {DUST_MM:g} mm",
    "dust colour": f"within {DUST_TOLERANCE} of the backing",
    "scrap at a side": f"in the first {TAIL_KEEP_MM:g} mm of the",
}
README_SKIPS = {"fringe", "wide tolerance", "shadow speck"}  # the README is short
CONCEPTS = (
    "full-width",
    "edge line",
    "white tail",
    "wedge",
    "1-bit",
    "sliver",
    "flush with",
    "neutral grey",
)
STALE = (
    "The top is never trimmed",
    "top is never trimmed",
    "95% of all the pixels",
    "never over what is not white",
    "starts within 20 mm of the bottom edge",
    "at most 1 mm of the band stays",
    "at most 1 mm of it stays",
    "joins a side of the strip through the pad",
    "joined to a side through the pad",
    "pale ink or a darker or not blue",
    "or a pencil on a slip of the backing's colour",
    "faded ink or pencil, not shadow",
)
TEXTS = {**DOCUMENTS, "trim docstring": trim.__doc__ or "", "guard docstring": guard.__doc__ or ""}


def flat(text: str) -> str:
    return " ".join(text.split())


def has_number(text: str, fact: str) -> bool:
    return re.search(r"(?<![\d.])" + re.escape(fact), flat(text).lower()) is not None


@pytest.mark.parametrize("fact", list(FACTS))
@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_numbers_of_the_band_rule_are_the_constants_of_the_code(name: str, fact: str) -> None:
    if name == "README" and fact in README_SKIPS:
        pytest.skip("the README gives the rule, not every constant")
    assert has_number(DOCUMENTS[name], FACTS[fact].lower()), FACTS[fact]


@pytest.mark.parametrize("concept", CONCEPTS)
@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_band_rule_is_described(name: str, concept: str) -> None:
    assert concept in flat(DOCUMENTS[name]).lower()


@pytest.mark.parametrize("stale", STALE)
@pytest.mark.parametrize("name", list(TEXTS))
def test_nothing_describes_the_band_rule_as_it_was(name: str, stale: str) -> None:
    assert stale.lower() not in flat(TEXTS[name]).lower()


@pytest.mark.parametrize("name", list(TEXTS))
def test_nothing_tells_the_history_of_the_rule_in_rounds(name: str) -> None:
    assert re.search(r"\bround \d", TEXTS[name], flags=re.IGNORECASE) is None
