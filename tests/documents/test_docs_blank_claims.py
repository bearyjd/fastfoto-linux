"""What the README and the design note say about fold creases and about loading the feeder."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import blank, marks

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_blank_rule_is_described_as_ignoring_faint_fold_creases(name: str) -> None:
    text = text_of(name)
    assert "faint fold creases" in text
    assert "faint line" in text
    assert "straight" in text
    assert f"within {marks.STRAIGHT_TOLERANCE_MM} mm of its axis" in text
    assert f"{round(marks.STRAIGHT_SHARE * 100)}%" in text
    assert f"{marks.STROKE_MAX_MM} mm" in text
    assert f"{marks.ELONGATION_MIN} times longer than wide" in text
    assert f"darker than {marks.FAINT_DARKEST}" in text
    assert "faint line with nothing beside it" in text
    assert f"more than {marks.INNER_MM} mm and at most {marks.OUTER_MM} mm" in text
    assert "alongside it" in text
    assert "the pieces of one crease lie end to end" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_dust_and_ink_on_a_crease_are_described(name: str) -> None:
    text = text_of(name)
    assert "a dark speck on a crease is dust" in text or "a speck under a millimetre" in text
    assert "dark ink touching one" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_limits_of_the_crease_rule_are_listed_exactly(name: str) -> None:
    text = text_of(name)
    assert (
        'a lone faint straight stroke ("l", "I", "1", "-", "!", the stem of an "i" or "j")' in text
    )
    assert "dashed or ruled lines" in text
    assert "text so pale" in text
    assert "only a few isolated stems register" in text
    assert "at sizes from 6 to 14 pt" in text
    assert "the tests pin 6 to 12 pt" in text
    assert f"tally more than about {marks.OUTER_MM} mm apart" in text
    assert "a bare tick whose hook is about 2 mm or shorter" in text
    assert f"lies within {marks.INNER_MM} mm of the near one's axis" in text
    assert 'a tight "=" in 10 pt' in text
    assert "a crease with a mark beside it keeps the page" in text
    assert "creases that cross are one big mark and keep the page" in text
    assert "a speck under a millimetre next to a crease segment under 2 mm long" in text
    assert "ink lying along a crease counts only where it leaves it" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_nothing_is_claimed_that_the_rule_no_longer_does(name: str) -> None:
    text = text_of(name)
    assert "never a page lost" not in text
    assert "touching a crease keeps the page" not in text
    assert "a dust speck touching a crease" not in text
    assert "so pencil handwriting keeps the page" not in text
    assert "pencil measured" not in text.lower()
    assert "pencil 110 to 150" not in text.lower()
    assert 'a faint straight single stroke ("l", "I", "-", "!", a ruled line)' not in text
    assert 'the stems of a faint "i", "j" or "ii"' not in text
    assert "signature wave are lines" not in text
    assert "thin faint line" not in text  # the line is straight as well as thin
    assert "pale and small" not in text  # the size does not matter: 6 to 14 pt
    assert "6 to 8 pt" not in text
    assert "three marks or fewer" not in text
    assert "bowed by 0.5 mm is not straight" not in text
    assert "LINE_MAX_MM" not in text
    assert "LINE_ASPECT" not in text


def test_pencil_110_to_150_is_called_a_test_value() -> None:
    design = text_of("design note")
    assert "pencil-like strokes darkest 110 to 150" in design
    assert "a test value, not a measurement" in design


def test_the_design_note_names_the_constants_of_the_rule() -> None:
    design = text_of("design note")
    names = (
        "STROKE_MAX_MM",
        "STRAIGHT_TOLERANCE_MM",
        "STRAIGHT_SHARE",
        "ELONGATION_MIN",
        "FAINT_DARKEST",
        "SPECK_MIN_MM",
        "DUST_HALO_MM",
        "MARK_MIN_MM",
        "INNER_MM",
        "OUTER_MM",
    )
    for name in names:
        assert hasattr(marks, name)
        assert f"`{name}`" in design


def test_the_design_note_explains_who_a_neighbour_is() -> None:
    design = text_of("design note")
    assert "a neighbour must itself be mark-sized" in design
    assert (
        "thin fragments beside the slanted artefact count only when they are mark-sized" in design
    )
    assert "thin fragments beside the slanted artefact are dust" not in design
    assert "any-spot" in design  # the variant that was tried and kept a real blank back


def test_the_design_note_sorts_the_limits_into_two_groups() -> None:
    design = text_of("design note")
    assert "**A page may be called blank**" in design
    assert "**A page is kept, on the conservative side**" in design
    assert "except the first two" not in design
    assert "(`OUTER_MM`, measured to the nearest pixel" in design


def test_the_design_note_states_the_sizes_of_a_mark_and_a_speck() -> None:
    design = text_of("design note")
    assert marks.MARK_MIN_MM == 1.0
    assert "a millimetre long" in design
    assert marks.MARK_MIN_AREA_MM2 == 0.3
    assert "a third of a square millimetre" in design
    assert f"{marks.SPECK_MIN_MM} mm wide" in design
    assert f"{marks.DUST_HALO_MM} mm" in design


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_loading_of_the_feeder_is_described(name: str) -> None:
    text = text_of(name)
    assert "face down, top edge first" in text
    assert "printed side is then scanned first" in text
    assert "checked on the FF-680W" in text


def test_the_scanners_png_is_described_as_carrying_its_resolution() -> None:
    design = text_of("design note")
    assert "carries its resolution" in text_of("README")
    assert "carries its resolution" in design
    assert "fallback resolution" in design  # kept for files that do not say
    assert "whether the PNG header carries" not in design
    assert "could not be checked without the scanner" not in design


def test_the_marks_module_documents_the_crease_rule() -> None:
    text = " ".join((marks.__doc__ or "").split())
    assert "fold crease" in text
    assert "straight" in text
    assert "lone faint straight stroke" in text
    assert '"1"' in text
    assert '"j"' in text
    assert 'a tight "="' in text
    assert "beside" in text
    assert "faint flat signature wave" not in text
    for name in (
        "STRAIGHT_SHARE",
        "STRAIGHT_TOLERANCE_MM",
        "STROKE_MAX_MM",
        "ELONGATION_MIN",
        "INNER_MM",
        "OUTER_MM",
    ):
        assert name in text


def test_the_blank_module_describes_the_straight_thin_line() -> None:
    text = (
        " ".join((blank.__doc__ or "").split())
        + " "
        + " ".join((blank.is_blank.__doc__ or "").split())
    )
    assert "straight" in text
    assert "thin" in text
    assert "faint fold crease" in text
    assert "beside" in text
