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
    assert holes.HOLE_DARKEST_MIN == 60
    assert holes.HOLE_TONE_MATCH == 30
    assert holes.HOLE_TINT == 12
    assert holes.OFFSET_SPREAD_MM == 0.5


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
def test_a_hole_is_grey_and_neutral_and_the_same_on_both_sides(name: str) -> None:
    text = text_of(name)
    assert f"darkest pixel is no darker than {holes.HOLE_DARKEST_MIN} on both sides" in text
    assert "(`HOLE_DARKEST_MIN`: print is darkest 0 to 12, real holes 89 to 106)" in text
    assert (
        f"within {holes.HOLE_TONE_MATCH} of each other (`HOLE_TONE_MATCH`: real holes 15)" in text
    )
    assert f"mean blue less red of its shape is within {holes.HOLE_TINT} of 0" in text
    assert "(`HOLE_TINT`: real holes 4)" in text
    assert "so printed or inked marks are never holes, whatever lies opposite" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_holes_of_a_page_share_one_registration(name: str) -> None:
    text = text_of(name)
    assert "When a page has two or more holes they share one registration" in text
    assert (
        f"agree within {holes.OFFSET_SPREAD_MM:g} mm (`OFFSET_SPREAD_MM`: real holes 0.1)" in text
    )
    assert "marks that only look alike land at arbitrary offsets inside the window" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_offset_tolerance_is_given_as_measured_for_small_and_large_holes(name: str) -> None:
    text = text_of(name)
    assert f"The window is {holes.SHIFT_MM:.1f} mm (`SHIFT_MM`)" in text
    assert (
        "a hole is found as far out as its overlap allows, so a bigger hole is found further"
        in text
    )
    assert "up to 2.5 mm for a staple hole of 1.8 mm" in text
    assert "up to 3.5 mm for a punched hole of 6 mm" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_limits_of_the_hole_rule_are_listed(name: str) -> None:
    text = text_of(name)
    zone = f"within {holes.EDGE_ZONE_MM:g} mm of an edge"
    assert "pencil and grey marks rely on shape, tint and registration" in text
    assert (
        f"the same symmetric mark at the mirrored spots of both sides, {zone}, "
        "on an otherwise blank back is taken for a hole"
    ) in text
    assert "Printed or inked marks are never holes" in text
    assert "A 1-bit page has no greys (a hole is as black as print)" in text
    assert (
        "Pairing is by page order, so `doc process` given pages that do not start with a front "
        "pairs them wrongly"
    ) in text
    assert "a back then meets another front, and is kept unless that front has a shape" in text
    assert "(the safe side;" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_a_marks_shape_is_the_whole_dark_shape_and_not_one_over_eight_millimetres(
    name: str,
) -> None:
    text = text_of(name)
    assert blank.BLANK_MARGIN_MM == 5.0
    assert (
        "A mark's shape is the whole dark shape that meets its box, cropped to its own "
        "bounding box, not clipped by the box or by the 5 mm blank margin"
    ) in text
    assert f"longer than {holes.HOLE_MAX_MM:g} mm" in text
    assert "a small mark joined to a long dark line is content" in text


def test_the_design_note_gives_the_real_page_result_of_the_shipped_rule() -> None:
    text = text_of("design note")
    assert "That was measured with the prototype." in text
    assert (
        "Re-run on the real pages, the rule as shipped before the tone, tint and registration "
        "checks left both real stapled backs blank and kept every text page"
    ) in text
    assert "has to be measured on the real pages again" not in text
    assert "On real pages the rule dropped" not in text


def test_the_design_note_gives_the_numbers_the_tone_tint_and_registration_were_set_from() -> None:
    text = text_of("design note")
    assert "darkest 89 to 100 on the judged side and 97 to 106 on its partner" in text
    assert "mean colour 122 to 139, blue less red at most 4" in text
    assert "0.68 to 1.19 mm" in text
    assert "overlap 0.59 to 0.87" in text
    assert "to within 0.1 mm" in text
    assert "darkest 0 to 12 (5th, 50th and 95th percentile 0, 0 to 2 and 9 to 12)" in text


def test_the_design_note_no_longer_says_a_punch_hole_always_keeps_the_page() -> None:
    assert "a punch hole or a scanner streak keeps the page" not in text_of("design note")


def test_the_module_text_names_the_rule_and_its_limits() -> None:
    text = squeezed(holes.__doc__)
    names = ("HOLE_MAX_MM", "EDGE_ZONE_MM", "HOLE_TONE", "SIZE_RATIO", "SHIFT_MM", "MATCH_IOU")
    for name in (*names, "HOLE_DARKEST_MIN", "HOLE_TONE_MATCH", "HOLE_TINT", "OFFSET_SPREAD_MM"):
        assert f"``{name}``" in text
    assert "The back of a sheet is its front flipped left to right and the top stays on top" in text
    assert "the same symmetric mark at the mirrored spots of both sides" in text
    assert "Print is never a hole" in text
    assert "share one registration" in text
    assert "A 1-bit page has no greys" in text
    assert "the pairing is by page order, so pages that do not start with a front" in text
    assert "One shape explains one mark" in text
    assert "not clipped by the box or by the blank margin" in text
    assert "a small mark joined to a long dark line is content" in text
    assert "whole dark shape" in squeezed(holes._shape_of.__doc__)


def test_the_blank_rule_text_gives_the_numbers() -> None:
    text = squeezed(blank.is_blank_beside.__doc__)
    assert f"({holes.HOLE_MAX_MM:g} mm)" in text
    assert f"({holes.EDGE_ZONE_MM:g} mm)" in text
    assert f"({holes.SHIFT_MM:.1f} mm)" in text
    assert f"({holes.MATCH_IOU:g})" in text
    assert f"darkest pixel {holes.HOLE_DARKEST_MIN} or paler" in text
    assert f"within {holes.HOLE_TONE_MATCH} of the other's" in text
    assert f"blue less red within {holes.HOLE_TINT}" in text
    assert f"within {holes.OFFSET_SPREAD_MM:g} mm of one registration" in text
