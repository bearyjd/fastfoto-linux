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


PAGE_NUMBER_CLAIM = (
    "A page number in Arabic digits set at 8 pt or more in a proportional Sans or Serif font has "
    "digits 2 to 3 mm tall (tested at 8 to 12 pt), over a staple hole, and not round discs, so in "
    "no grey is it a hole"
)
# What the verification measured to drop the lone folio of a blank back, beyond the digits of a
# numeral under 8 pt: glyphs only x-height tall, and monospace digits.
SMALL_GLYPH_LIMIT = (
    'grey glyphs only x-height tall, lowercase roman folios such as "x", "v" and "o", up to '
    "about 9 pt in Sans or 11 pt in Serif, at the mirrored spot of a similar grey glyph on a grey "
    'front (as measured, "ix" on the front and "x" on the back), and grey monospace digits at '
    "8 to 9 pt"
)
LONE_FOLIO_LIMIT = "drops only the lone folio of an otherwise blank back"


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


def squeezed(text: str | None) -> str:
    return " ".join((text or "").split())


def test_the_constants_are_the_ones_the_rule_was_measured_with() -> None:
    assert holes.STAPLE_MAX_MM == 1.8
    assert holes.PUNCH_MIN_MM == 4.0
    assert holes.HOLE_MAX_MM == 8.0
    assert holes.PUNCH_ASPECT_MIN == 0.8
    assert holes.PUNCH_FILL_MIN == 0.6
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
    assert "is a hole when its whole shape is the size of a staple hole" in text
    assert "or of a punched hole" in text
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
def test_a_hole_is_a_staple_hole_or_a_round_punched_disc(name: str) -> None:
    text = text_of(name)
    assert (
        f"A staple hole is at most {holes.STAPLE_MAX_MM:g} mm long (`STAPLE_MAX_MM`; "
        "real ones are 0.6 to 1.35 mm)"
    ) in text
    assert (
        f"A punched hole is a round disc {holes.PUNCH_MIN_MM:g} to {holes.HOLE_MAX_MM:g} mm long "
        "(`PUNCH_MIN_MM`, `HOLE_MAX_MM`; punched holes are about 6 mm)"
    ) in text
    assert f"short side at least {holes.PUNCH_ASPECT_MIN:g} of its long one" in text
    assert "(`PUNCH_ASPECT_MIN`)" in text
    assert f"at least {holes.PUNCH_FILL_MIN:g} filled (`PUNCH_FILL_MIN`; a disc fills 0.78)" in text
    assert (
        'Anything in between, and a long thin or hollow mark over 1.8 mm (a "0", an "o" of print), '
        "is never a hole"
    ) in text


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
    assert "so black print, pen, stamps and ink of a colour are not holes" in text
    assert PAGE_NUMBER_CLAIM in text
    assert "A page number set at 8 pt or more" not in text
    assert "whatever lies opposite" not in text
    assert "no longer matters" not in text


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
    assert "pencil and grey marks rely on size, shape, tint and registration" in text
    assert (
        f"the same symmetric mark at the mirrored spots of both sides, {zone}, "
        "on an otherwise blank back is taken for a hole"
    ) in text
    assert (
        'That includes smaller grey marks: a grey "." or "-" or "o" of pencil or of grey print '
        "(a whole shape of at most 1.8 mm, as the digits of a numeral set under 8 pt can be)"
    ) in text
    assert "at the mirrored spot of a grey mark on the other side" in text
    assert SMALL_GLYPH_LIMIT in text
    assert LONE_FOLIO_LIMIT in text
    assert "Black print and ink are never holes" in text
    assert "A 1-bit page has no greys (a hole is as black as print)" in text
    assert "holes 216 mm apart (a three-hole punch on Letter paper)" in text
    assert "holes 180 mm" not in text
    assert "within about 0.15 degrees of each other" in text
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


def test_the_design_note_gives_the_numbers_the_size_classes_were_set_from() -> None:
    text = text_of("design note")
    assert "17 matched real staple holes across 5 scans" in text
    assert "whole shape 0.59 to 1.35 mm long and 0.42 to 0.93 mm short" in text
    assert "aspect 0.57 to 1.0, fill 0.29 to 0.78, darkest 86 to 108" in text
    assert "digits of a page number at 8 to 12 pt are 2.0 to 3.0 mm tall" in text
    assert "`STAPLE_MAX_MM` 1.8 is a third above the largest real hole" in text
    assert "0.543 against 0.5" in text
    assert "14 backs were dropped at 7.5 pt (0.6 %) and 32 at 7 pt (1.3 %)" in text
    assert "none at 8 pt and up" in text


def test_the_design_note_keeps_a_page_number_only_in_proportional_digits() -> None:
    text = text_of("design note")
    assert (
        "a page number in Arabic digits set at 8 pt or more in a proportional Sans or Serif font "
        "keeps its page in any grey"
    ) in text
    assert "a page number set at 8 pt or more keeps its page in any grey" not in text
    assert (
        "The digits of a page number in Arabic digits at 8 pt and more in a proportional Sans or "
        "Serif font are over the staple size and are not discs; grey monospace digits at 8 to 9 pt "
        "can be dropped (the limits, below)"
    ) in text
    assert "The digits of a page number at 8 pt and more are over the staple size" not in text


def test_the_design_note_no_longer_says_a_punch_hole_always_keeps_the_page() -> None:
    assert "a punch hole or a scanner streak keeps the page" not in text_of("design note")


def test_the_module_text_names_the_rule_and_its_limits() -> None:
    text = squeezed(holes.__doc__)
    names = ("HOLE_MAX_MM", "EDGE_ZONE_MM", "HOLE_TONE", "SIZE_RATIO", "SHIFT_MM", "MATCH_IOU")
    for name in (*names, "HOLE_DARKEST_MIN", "HOLE_TONE_MATCH", "HOLE_TINT", "OFFSET_SPREAD_MM"):
        assert f"``{name}``" in text
    for name in ("STAPLE_MAX_MM", "PUNCH_MIN_MM", "PUNCH_ASPECT_MIN", "PUNCH_FILL_MIN"):
        assert f"``{name}``" in text
    assert (
        'Anything in between, and a long thin or hollow mark over 1.8 mm (a "0", an "o" of print), '
        "is never a hole"
    ) in text
    assert PAGE_NUMBER_CLAIM in text
    assert "A page number set at 8 pt or more" not in text
    assert "whatever lies opposite" not in text
    assert "no longer matters" not in text
    assert "smaller grey marks" in text
    assert SMALL_GLYPH_LIMIT in text
    assert LONE_FOLIO_LIMIT in text
    assert "The back of a sheet is its front flipped left to right and the top stays on top" in text
    assert "the same symmetric mark at the mirrored spots of both sides" in text
    assert "Black print is never a hole" in text
    assert "share one registration" in text
    assert "A 1-bit page has no greys" in text
    assert "holes 216 mm apart (a three-hole punch on Letter paper)" in text
    assert "the pairing is by page order, so pages that do not start with a front" in text
    assert "One shape explains one mark" in text
    assert "not clipped by the box or by the blank margin" in text
    assert "a small mark joined to a long dark line is content" in text
    assert "whole dark shape" in squeezed(holes._shape_of.__doc__)


def test_the_blank_rule_text_gives_the_numbers() -> None:
    text = squeezed(blank.is_blank_beside.__doc__)
    assert f"``holes.STAPLE_MAX_MM`` ({holes.STAPLE_MAX_MM:g} mm)" in text
    assert f"({holes.PUNCH_MIN_MM:g} to {holes.HOLE_MAX_MM:g} mm)" in text
    assert f"({holes.EDGE_ZONE_MM:g} mm)" in text
    assert f"({holes.SHIFT_MM:.1f} mm)" in text
    assert f"({holes.MATCH_IOU:g})" in text
    assert f"darkest pixel {holes.HOLE_DARKEST_MIN} or paler" in text
    assert f"within {holes.HOLE_TONE_MATCH} of the other's" in text
    assert f"blue less red within {holes.HOLE_TINT}" in text
    assert f"within {holes.OFFSET_SPREAD_MM:g} mm of one registration" in text
