"""What the README, the design note and the docstrings say about holes through the paper, and
about pairing pages, is what the rule does: the constants are pinned, and so are the limits."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import blank, holes

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


def squeezed(text: str | None) -> str:
    return " ".join((text or "").split())


def test_the_constants_are_the_ones_the_rule_was_measured_with() -> None:
    assert holes.HOLE_MAX_MM == 8.0
    assert holes.EDGE_ZONE_MM == 25.0
    assert holes.SHIFT_MM == 2.0
    assert holes.MATCH_IOU == 0.5
    assert holes.SIZE_RATIO == 1.5
    assert holes.HOLE_TONE == 160


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_hole_rule_is_described_with_its_constants(name: str) -> None:
    text = text_of(name)
    assert "A hole through the paper does not keep a page" in text
    assert f"its longer side is at most {holes.HOLE_MAX_MM:g} mm" in text
    assert f"within {holes.EDGE_ZONE_MM:g} mm of an edge of the page" in text
    assert "the other side of the same sheet has a dark shape of the same size" in text
    assert "at the mirrored spot" in text
    assert (
        "its front flipped left to right, so x becomes the frame width less x and y stays" in text
    )
    assert "with each side's trim offsets added back" in text
    assert f"darker than {holes.HOLE_TONE} on the darkest colour channel" in text
    assert f"within {holes.SIZE_RATIO:g} times that of the mark's" in text
    assert f"shifted by up to {holes.SHIFT_MM:.1f} mm in either direction" in text
    assert f"overlap by at least {holes.MATCH_IOU:g} (intersection over union)" in text
    assert "One shape explains one mark" in text
    assert (
        "A page is blank when it has no counted mark, or when every counted mark is a hole" in text
    )


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_pairing_is_described(name: str) -> None:
    text = text_of(name)
    assert "Pages are paired in order, 1+2, 3+4" in text
    assert "`doc scan` pairs the pages it scans unless `--simplex`" in text
    assert "`doc process` pairs the pages it is given unless `--simplex`" in text
    assert "give it pages that start with a front" in text
    assert "An odd last page has no partner" in text
    assert "at most two are in memory" in text or "two pages in memory at most" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_limits_of_the_hole_rule_are_listed(name: str) -> None:
    text = text_of(name)
    zone = f"within {holes.EDGE_ZONE_MM:g} mm of an edge"
    assert (
        f"the same symmetric mark printed at the mirrored spots of both sides, {zone}, "
        "on an otherwise blank back is taken for a hole"
    ) in text
    assert (
        "Pairing is by page order, so `doc process` given pages that do not start with a front "
        "pairs them wrongly"
    ) in text
    assert "a back then meets another front, and is kept unless that front has a shape" in text
    assert "(the safe side;" in text


def test_the_design_note_no_longer_says_a_punch_hole_always_keeps_the_page() -> None:
    assert "a punch hole or a scanner streak keeps the page" not in text_of("design note")


def test_the_module_text_names_the_rule_and_its_limits() -> None:
    text = squeezed(holes.__doc__)
    for name in ("HOLE_MAX_MM", "EDGE_ZONE_MM", "HOLE_TONE", "SIZE_RATIO", "SHIFT_MM", "MATCH_IOU"):
        assert f"``{name}``" in text
    assert "The back of a sheet is its front flipped left to right and the top stays on top" in text
    assert "the same symmetric mark printed at the mirrored spots of both sides" in text
    assert "the pairing is by page order, so pages that do not start with a front" in text
    assert "One shape explains one mark" in text


def test_the_blank_rule_text_gives_the_numbers() -> None:
    text = squeezed(blank.is_blank_beside.__doc__)
    assert f"({holes.HOLE_MAX_MM:g} mm)" in text
    assert f"({holes.EDGE_ZONE_MM:g} mm)" in text
    assert f"({holes.SHIFT_MM:.1f} mm)" in text
    assert f"({holes.MATCH_IOU:g})" in text
