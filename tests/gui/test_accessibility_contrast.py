"""WCAG 2.x contrast of the colours the QML draws text and keyboard cues with.

The QML takes its colours from the Kirigami theme, which follows the user's colour scheme, so
the check pins two real schemes (see ``tests/gui/qml_colours.py``), reads every colour binding
of every ``.qml`` file, and computes the ratio against every background it can sit on.

The scan fails closed: a colour binding it cannot read (a multi-line expression it does not
understand, ``palette.*``, a colour set from JavaScript, ``Qt.rgba``, a literal) is a failure,
unless it is on the documented allow-list in ``qml_colours.ALLOWED``.
"""

import re

import pytest

from tests.gui.qml_colours import (
    ALLOWED,
    BACKGROUNDS,
    NON_TEXT_MINIMUM,
    QML_DIR,
    SCHEMES,
    TEXT_MINIMUM,
    check_directory,
    check_source,
    contrast,
    scan_directory,
    scan_source,
)


def test_the_contrast_formula_matches_the_wcag_reference_values() -> None:
    assert contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert contrast((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)
    assert contrast((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)


def test_the_pinned_schemes_are_the_real_breeze_values() -> None:
    light = SCHEMES["Breeze Light"]
    assert light["view"] == (252, 252, 252)  # [Colors:View] BackgroundNormal in BreezeLight.colors
    assert light["window"] == (239, 240, 241)
    assert SCHEMES["Breeze Dark"]["view"] == (20, 22, 24)


def test_the_qml_files_have_no_unsupported_or_too_faint_colour() -> None:
    assert check_directory() == []


def test_the_scan_finds_every_kind_of_binding() -> None:
    found = scan_directory()
    assert len(found) > 45
    assert {b.prop for b in found} >= {"color", "border.color"}
    assert any("Qt.tint" in b.expression for b in found)
    assert any("Qt.alpha" in b.expression for b in found)
    assert any(b.expression.startswith('"#') for b in found)


def test_every_allow_list_entry_still_exists_and_says_why() -> None:
    present = {(b.file, b.expression) for b in scan_directory()}
    for key, reason in ALLOWED.items():
        assert key in present, f"stale allow-list entry {key}"
        assert len(reason) > 20, f"{key} needs a reason"


def problems(source: str, name: str = "Sample.qml") -> list[str]:
    return check_source(name, source)


GOOD_HINT = "Label { color: Qt.alpha(Kirigami.Theme.textColor, 0.75) }"


def test_a_supported_binding_passes() -> None:
    assert problems(GOOD_HINT) == []
    assert problems("Label { color: Kirigami.Theme.textColor }") == []
    assert problems("Rectangle { color: Kirigami.Theme.backgroundColor }") == []
    assert (
        problems('Rectangle { color: "transparent"; border.color: Kirigami.Theme.textColor }') == []
    )
    assert problems("property color hint: Kirigami.Theme.textColor") == []


def test_a_literal_colour_instead_of_the_hint_is_a_failure() -> None:
    """The mutation Codex found: the hint of ReviewPage.qml replaced by white."""
    assert problems('Label { color: "#ffffff" }', "ReviewPage.qml")
    assert problems("Label { color: 'white' }")


def test_a_raw_theme_colour_as_text_is_a_failure_by_its_ratio() -> None:
    for role in ("disabledTextColor", "negativeTextColor", "neutralTextColor"):
        assert problems(f"Label {{ color: Kirigami.Theme.{role} }}"), role


def test_a_faint_blend_is_a_failure() -> None:
    assert problems("Label { color: Qt.alpha(Kirigami.Theme.textColor, 0.4) }")
    assert problems(
        "Label { color: Qt.tint(Kirigami.Theme.negativeTextColor,"
        " Qt.alpha(Kirigami.Theme.textColor, 0.02)) }"
    )


def test_a_multi_line_binding_is_read_to_its_end() -> None:
    bad = """Label {
        color: row.warning
            ? Kirigami.Theme.textColor
            : Kirigami.Theme.disabledTextColor
    }"""
    assert problems(bad)
    good = """Label {
        color: row.warning
            ? Qt.alpha(Kirigami.Theme.textColor, 0.75)
            : Kirigami.Theme.textColor
    }"""
    assert problems(good) == []
    assert problems(
        "Label {\n  color: Qt.tint(Kirigami.Theme.neutralTextColor,\n"
        "    Qt.alpha(Kirigami.Theme.textColor, 0.02))\n}"
    )


@pytest.mark.parametrize(
    "source",
    [
        "Label { color: Qt.rgba(1, 1, 1, 1) }",
        "Label { color: Qt.darker(Kirigami.Theme.textColor) }",
        "Label { color: someFunction() }",
        "Label { color: Kirigami.Theme.unknownColor }",
        'Label { palette.buttonText: "red" }',
        "Label { palette: control.palette }",
        'Label { Component.onCompleted: label.color = "#ffffff" }',
        'Label { onClicked: { parent.border.color = "#fff" } }',
        "property color hint: Qt.rgba(0, 0, 0, 1)",
        "Label { textColor: 'red' }",
    ],
)
def test_a_binding_the_scan_cannot_read_is_a_failure_not_skipped(source: str) -> None:
    assert problems(source), source


def test_the_allow_list_is_keyed_by_file_and_exact_expression() -> None:
    literal = 'Rectangle { border.color: "#ffffff" }'
    assert problems(literal, "PhotoEditCanvas.qml") == []
    assert problems(literal, "ReviewPage.qml")
    assert problems('Rectangle { border.color: "#fffffe" }', "PhotoEditCanvas.qml")


def test_the_focus_colour_is_not_enough_for_a_border_on_breeze_light() -> None:
    assert problems("Rectangle { border.color: Kirigami.Theme.highlightColor }")


def test_scan_source_gives_line_numbers() -> None:
    (binding,) = scan_source("A.qml", "Item {\n\n  Label { color: Kirigami.Theme.textColor }\n}")
    assert (binding.file, binding.line, binding.prop) == ("A.qml", 3, "color")


@pytest.mark.parametrize("scheme_name", sorted(SCHEMES))
def test_the_raw_theme_roles_this_change_replaced_are_computed_to_be_too_faint(
    scheme_name: str,
) -> None:
    """The ratios of the raw roles, from the pinned palette (so the check can really fail)."""
    scheme = SCHEMES[scheme_name]
    ratios = {
        role: min(contrast(scheme[role], scheme[b]) for b in BACKGROUNDS)
        for role in ("inactive", "negative", "neutral")
    }
    assert min(ratios.values()) > 1.0
    if scheme_name == "Breeze Light":
        assert all(ratio < TEXT_MINIMUM for ratio in ratios.values()), ratios
    else:
        assert ratios["negative"] < TEXT_MINIMUM, ratios


@pytest.mark.parametrize("scheme_name", sorted(SCHEMES))
def test_the_selected_review_page_border_is_a_3_to_1_cue(scheme_name: str) -> None:
    scheme = SCHEMES[scheme_name]
    expressions = [b.expression for b in scan_source("ReviewCell.qml", read("ReviewCell.qml"))]
    assert any(e.startswith("cell.selected ? Kirigami.Theme.textColor :") for e in expressions)
    for background in BACKGROUNDS:
        assert contrast(scheme["text"], scheme[background]) >= NON_TEXT_MINIMUM
        # the unselected outline (the inactive text role) is a visible edge too, with less room
        assert contrast(scheme["inactive"], scheme[background]) >= NON_TEXT_MINIMUM


def read(file_name: str) -> str:
    return (QML_DIR / file_name).read_text()


def block_after(text: str, opener: str) -> str:
    """The brace-matched body of the first ``opener {`` in ``text`` (any indentation)."""
    start = re.search(opener + r"\s*\{", text)
    assert start, opener
    depth, index = 1, start.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        index += 1
    return text[start.end() : index - 1]


def test_block_after_finds_the_body_at_any_indentation() -> None:
    assert "b" in block_after(
        "x {\n  highlight: Rectangle {\n a { } b\n }\n}", "highlight: Rectangle"
    )
    assert "b" in block_after("highlight: Rectangle { a { } b }", "highlight: Rectangle")


@pytest.mark.parametrize("file_name", ["ResultsView.qml", "DocumentsView.qml"])
def test_the_keyboard_position_in_a_list_is_outlined_not_only_tinted(file_name: str) -> None:
    block = block_after(read(file_name), r"highlight:\s*Rectangle")
    width = re.search(r"border\.width:\s*(\d+)", block)
    assert width and int(width.group(1)) >= 2
    assert "border.color: Kirigami.Theme.textColor" in block


@pytest.mark.parametrize("file_name", sorted(p.name for p in QML_DIR.glob("*.qml")))
def test_every_busy_indicator_and_progress_bar_is_named(file_name: str) -> None:
    """Includes those inside dialogs, which the window-level sweep cannot reach."""
    text = read(file_name)
    for kind in ("BusyIndicator", "ProgressBar"):
        for match in re.finditer(rf"QQC2\.{kind}\s*\{{", text):
            body = block_after(text[match.start() :], rf"QQC2\.{kind}")
            assert "Accessible.name:" in body, f"{file_name}: unnamed {kind}"
