"""What the README, the design note and the docstrings say about the backing band is what the
code does: its structure, what is cut, and the limits (side slivers, a bar in the backing colour).
"""

from pathlib import Path

import pytest

from fastfoto_linux.documents import band, trim

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
    "band docstring": band.__doc__ or "",
}
CLAIMS = (
    "full-width backing band",
    "pad of pure white",
    "never through the edge line",
    "at most 1 mm of the band stays",
    "a band of 3 to 20 mm at the bottom and of 1 to 4 mm at the top",
    "side slivers of up to 2 mm are left",
    "a full-width bar in the backing colour at the top or bottom edge is cut",
    "grey and 1-bit pages are not cut by the band rule",
    "the blank-page margin is measured in full from the new edge",
)
STALE = (
    "The top is never trimmed",
    "top is never trimmed",
)


@pytest.mark.parametrize("claim", CLAIMS)
@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_band_rule_is_described(name: str, claim: str) -> None:
    assert claim in " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("stale", STALE)
@pytest.mark.parametrize("name", [*DOCUMENTS, "trim docstring"])
def test_the_top_is_no_longer_described_as_never_trimmed(name: str, stale: str) -> None:
    text = trim.__doc__ or "" if name == "trim docstring" else DOCUMENTS[name]
    assert stale not in " ".join(text.split())
