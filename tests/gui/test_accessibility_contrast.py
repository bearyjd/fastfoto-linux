"""WCAG 2.x contrast of the colours the QML draws text and keyboard cues with.

The QML takes its colours from the Kirigami theme, which follows the user's colour scheme, so
the check pins two real schemes (the values in KDE's ``BreezeLight.colors`` and
``BreezeDark.colors``, sections ``[Colors:Window]`` and ``[Colors:View]``) and computes the
ratio of every text colour the QML can use against every background it can sit on. Colours of
the QML source are read from the files, so a new raw ``disabledTextColor`` text fails here.

Not covered, and said so in docs/accessibility.md: the eye markers on a photo (their colour
sits on the photo, which is unknown here), the system focus ring of the controls (drawn by the
style), and the theme's derived ``negativeBackgroundColor`` (computed by KDE at run time).
"""

import re
from pathlib import Path

import pytest

QML_DIR = Path(__file__).resolve().parents[2] / "src/fastfoto_linux/gui/qml"
Rgb = tuple[float, float, float]

# BreezeLight.colors / BreezeDark.colors from KDE Plasma (RGB 0-255).
SCHEMES: dict[str, dict[str, Rgb]] = {
    "Breeze Light": {
        "window": (239, 240, 241),
        "window_alt": (227, 229, 231),
        "view": (255, 255, 255),
        "view_alt": (247, 247, 247),
        "text": (35, 38, 41),
        "inactive": (112, 125, 138),
        "negative": (218, 68, 83),
        "neutral": (246, 116, 0),
    },
    "Breeze Dark": {
        "window": (32, 35, 38),
        "window_alt": (41, 44, 48),
        "view": (20, 22, 24),
        "view_alt": (29, 31, 34),
        "text": (252, 252, 252),
        "inactive": (161, 169, 177),
        "negative": (218, 68, 83),
        "neutral": (246, 116, 0),
    },
}
BACKGROUNDS = ("window", "window_alt", "view", "view_alt")
TEXT_MINIMUM = 4.5  # WCAG 1.4.3, normal text
NON_TEXT_MINIMUM = 3.0  # WCAG 1.4.11, borders and focus cues
RAW_ROLES = ("disabledTextColor", "negativeTextColor", "neutralTextColor", "positiveTextColor")


def luminance(color: Rgb) -> float:
    def channel(value: float) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: Rgb, b: Rgb) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def blend(front: Rgb, back: Rgb, alpha: float) -> Rgb:
    """``front`` at ``alpha`` over ``back`` (what the renderer shows for a translucent colour)."""
    return tuple(f * alpha + b * (1 - alpha) for f, b in zip(front, back, strict=True))  # type: ignore[return-value]


def tint(base: Rgb, front: Rgb, alpha: float) -> Rgb:
    """``Qt.tint(base, Qt.alpha(front, alpha))``: per channel, ``base`` at 0 and ``front`` at 1."""
    return blend(front, base, alpha)


def test_the_contrast_formula_matches_the_wcag_reference_values() -> None:
    assert contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert contrast((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)
    assert contrast((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)


HINT = re.compile(r"Qt\.alpha\(Kirigami\.Theme\.textColor,\s*([\d.]+)\)")
MIXED = re.compile(
    r"Qt\.tint\(Kirigami\.Theme\.(negative|neutral)TextColor,\s*"
    r"Qt\.alpha\(Kirigami\.Theme\.textColor,\s*([\d.]+)\)\)"
)
APPROVED_BLEND = re.compile(f"{MIXED.pattern}|{HINT.pattern}")


def qml_colour_lines() -> list[tuple[str, int, str]]:
    """``color:`` bindings (not ``border.color``) of every QML file: (file, line, expression)."""
    found = []
    for path in sorted(QML_DIR.glob("*.qml")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            match = re.match(r"\s*color:\s*(.+?)\s*$", line)
            if match:
                found.append((path.name, number, match.group(1)))
    return found


def test_the_qml_has_colour_bindings_to_check() -> None:
    assert len(qml_colour_lines()) > 20


def test_no_text_uses_a_raw_theme_colour_that_misses_the_contrast_minimum() -> None:
    """disabled/negative/neutral theme text is 2.5-4.3:1 on Breeze Light; only blends are used."""
    offenders = []
    for name, number, expression in qml_colour_lines():
        rest = APPROVED_BLEND.sub("", expression)
        if any(role in rest for role in RAW_ROLES):
            offenders.append(f"{name}:{number}: {expression}")
    assert offenders == []


def used_text_colours(scheme: dict[str, Rgb], background: str) -> dict[str, Rgb]:
    """Every text colour the QML draws, resolved in ``scheme`` over ``background``."""
    base = scheme[background]
    colours: dict[str, Rgb] = {"textColor": scheme["text"]}
    for name, number, expression in qml_colour_lines():
        for match in HINT.finditer(expression):
            alpha = float(match.group(1))
            colours[f"{name}:{number} hint"] = blend(scheme["text"], base, alpha)
        for match in MIXED.finditer(expression):
            role, ratio = match.group(1), float(match.group(2))
            colours[f"{name}:{number} {role}"] = tint(scheme[role], scheme["text"], ratio)
    return colours


@pytest.mark.parametrize("scheme_name", sorted(SCHEMES))
@pytest.mark.parametrize("background", BACKGROUNDS)
def test_every_text_colour_reaches_4_5_to_1_on_every_background(
    scheme_name: str, background: str
) -> None:
    scheme = SCHEMES[scheme_name]
    colours = used_text_colours(scheme, background)
    assert len(colours) > 5, "the hint and the status blends are found in the QML"
    low = {
        label: round(contrast(colour, scheme[background]), 2)
        for label, colour in colours.items()
        if contrast(colour, scheme[background]) < TEXT_MINIMUM
    }
    assert low == {}


@pytest.mark.parametrize("scheme_name", sorted(SCHEMES))
def test_the_raw_theme_colours_this_change_replaced_really_were_too_faint(
    scheme_name: str,
) -> None:
    """Keeps the check honest: at least one raw role fails on Breeze Light (so it can fail)."""
    scheme = SCHEMES[scheme_name]
    raw = [scheme["inactive"], scheme["negative"], scheme["neutral"]]
    worst = min(contrast(c, scheme[b]) for c in raw for b in BACKGROUNDS)
    if scheme_name == "Breeze Light":
        assert worst < TEXT_MINIMUM
    assert worst > 1.0


def border_expressions(file_name: str) -> list[str]:
    text = (QML_DIR / file_name).read_text()
    return re.findall(r"^\s*border\.color:\s*(.+?)\s*$", text, re.MULTILINE)


@pytest.mark.parametrize("scheme_name", sorted(SCHEMES))
def test_the_selected_review_page_border_is_a_3_to_1_cue(scheme_name: str) -> None:
    scheme = SCHEMES[scheme_name]
    selected = "Kirigami.Theme.textColor"
    expressions = border_expressions("ReviewCell.qml")
    assert any(e.startswith(f"cell.selected ? {selected} :") for e in expressions)
    for background in BACKGROUNDS:
        assert contrast(scheme["text"], scheme[background]) >= NON_TEXT_MINIMUM
        # the unselected outline (inactive text) is also a visible edge
        assert contrast(scheme["inactive"], scheme[background]) >= NON_TEXT_MINIMUM


@pytest.mark.parametrize("file_name", ["ResultsView.qml", "DocumentsView.qml"])
def test_the_keyboard_position_in_a_list_is_outlined_not_only_tinted(file_name: str) -> None:
    text = (QML_DIR / file_name).read_text()
    match = re.search(r"highlight:\s*Rectangle\s*\{(.*?)\n\s{12}\}", text, re.DOTALL)
    assert match, f"{file_name} marks the current item"
    block = match.group(1)
    assert "border.width" in block
    assert "border.color: Kirigami.Theme.textColor" in block
