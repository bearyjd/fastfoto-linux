"""A fail-closed reader of the colour bindings in the QML, and the WCAG maths to check them.

Two real colour schemes are pinned (the values in KDE's ``BreezeLight.colors`` and
``BreezeDark.colors``, sections ``[Colors:Window]`` and ``[Colors:View]``). Every ``color:`` or
``border.color:`` style binding of a ``.qml`` file is read, multi-line ones included, and
evaluated in both schemes over each background the colour can sit on.

Fail closed: a binding that cannot be read, or that names a colour source the reader does not
know (``palette``, ``Qt.rgba``, ``Qt.darker``, a function, a colour set from JavaScript), is a
problem, not a pass. Colours that cannot be checked against the theme (they sit on a photo)
are listed with their reason in ``ALLOWED``, keyed by file and exact expression, so editing
one makes it a problem again.
"""

import re
from dataclasses import dataclass
from pathlib import Path

Rgb = tuple[float, float, float]

QML_DIR = Path(__file__).resolve().parents[2] / "src/fastfoto_linux/gui/qml"

SCHEMES: dict[str, dict[str, Rgb]] = {
    "Breeze Light": {
        "window": (239, 240, 241),
        "window_alt": (227, 229, 231),
        "view": (252, 252, 252),
        "view_alt": (247, 247, 247),
        "text": (35, 38, 41),
        "inactive": (112, 125, 138),
        "negative": (218, 68, 83),
        "neutral": (246, 116, 0),
        "positive": (39, 174, 96),
        "focus": (61, 174, 233),
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
        "positive": (39, 174, 96),
        "focus": (61, 174, 233),
    },
}
BACKGROUNDS = ("window", "window_alt", "view", "view_alt")
TEXT_MINIMUM = 4.5  # WCAG 1.4.3, normal text
NON_TEXT_MINIMUM = 3.0  # WCAG 1.4.11, borders and focus cues

# Kirigami.Theme roles that are text/line colours -> the scheme entry that pins them.
FOREGROUND_ROLES = {
    "textColor": "text",
    "disabledTextColor": "inactive",
    "negativeTextColor": "negative",
    "neutralTextColor": "neutral",
    "positiveTextColor": "positive",
    "highlightColor": "focus",
}
# Roles that are fills: text drawn on them is checked where the text colour is.
FILL_ROLES = {"backgroundColor", "alternateBackgroundColor", "negativeBackgroundColor"}
NAMED = {
    "transparent": None,
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "orange": (255, 165, 0),
}

_Q = r"""(?:"[^"]*"|'[^']*')"""
TINT = re.compile(
    r"Qt\.tint\(\s*Kirigami\.Theme\.(\w+)\s*,\s*Qt\.alpha\(\s*Kirigami\.Theme\.(\w+)\s*,"
    r"\s*([\d.]+)\s*\)\s*\)"
)
ALPHA = re.compile(r"Qt\.alpha\(\s*Kirigami\.Theme\.(\w+)\s*,\s*([\d.]+)\s*\)")
ROLE = re.compile(r"Kirigami\.Theme\.(\w+)")
HEX = re.compile(r"""["']#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})["']""")
WORD = re.compile(_Q)
COMPARISON = re.compile(r"[=!]==?\s*" + _Q)
LEFTOVER = re.compile(r"\bQt\.|\bKirigami\.|#[0-9a-fA-F]{3,8}\b|\bpalette\b|\w*[cC]olor\b")
BINDING = re.compile(
    r"(?:^|[{;])[ \t]*((?:\w+\.)*(?:\w*[cC]olor|palette(?:\.\w+)*)"
    r"|(?:(?:readonly|required|default)[ \t]+)*property[ \t]+color[ \t]+\w+)"
    r"\s*:(?!:)",
    re.MULTILINE,
)
JS_ASSIGN = re.compile(r"[\w.]*(?:[cC]olor|palette)(?:\.\w+)*\s*=(?!=)")
CONTINUES = ("?", ":", "&&", "||", "+", "-", "*", "/", ",", "(", "[")

# Colours that cannot be checked against the theme, with the reason. Key: (file, expression).
_PHOTO = "drawn over the photo, whose pixels are unknown here; paired with a symbol or a width"
ALLOWED: dict[tuple[str, str], str] = {
    ("PhotoEditCanvas.qml", '"#ffffff"'): f"selection and crop outline {_PHOTO}",
    ("PhotoEditCanvas.qml", '"white"'): f"rubber band outline {_PHOTO}",
    (
        "PhotoEditCanvas.qml",
        'modelData.id === canvas.selectedId ? "#ffffff" : '
        '(modelData.accepted ? "#75d69c" : "#ffcd70")',
    ): f"eye marker outline {_PHOTO} (and a check or cross says accepted or rejected)",
    ("PhotoEditCanvas.qml", "parent.border.color"): (
        "the status symbol takes its marker's outline colour, over the photo"
    ),
    ("PreviewDialog.qml", 'dialog.cropMode ? Kirigami.Theme.highlightColor : "#ffffff"'): (
        f"crop rectangle outline {_PHOTO}"
    ),
    ("ReviewCell.qml", "Kirigami.Theme.negativeTextColor"): (
        "box drawn around a mark on the page thumbnail, over the page picture"
    ),
    ("PhotoEditPage.qml", "control.palette"): (
        "hands the control's own palette to a part; the app picks no colour"
    ),
    ("PhotoGeometryControls.qml", "angleBox.palette"): (
        "hands the spin box's own palette to a part; the app picks no colour"
    ),
}


@dataclass(frozen=True)
class Binding:
    file: str
    line: int
    prop: str
    expression: str


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
    r, g, b = (f * alpha + k * (1 - alpha) for f, k in zip(front, back, strict=True))
    return (r, g, b)


def tint(base: Rgb, front: Rgb, alpha: float) -> Rgb:
    """``Qt.tint(base, Qt.alpha(front, alpha))``: per channel, ``base`` at 0 and ``front`` at 1."""
    return blend(front, base, alpha)


def _value_end(text: str, start: int) -> int:
    """Where the binding value that begins at ``start`` ends (multi-line aware)."""
    depth, index, quote = 0, start, ""
    while index < len(text):
        char = text[index]
        if quote:
            index += 2 if char == "\\" else 1
            quote = "" if char == quote else quote
            continue
        if char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return index
            depth -= 1
        elif depth == 0 and (char == ";" or (char == "\n" and not _continues(text, start, index))):
            return index
        elif char == "/" and text[index : index + 2] == "//":
            index = text.find("\n", index) - 1 if "\n" in text[index:] else len(text) - 1
        index += 1
    return len(text)


def _continues(text: str, start: int, newline: int) -> bool:
    so_far = text[start:newline].rstrip()
    following = text[newline:].lstrip()
    return so_far.endswith(CONTINUES) or following.startswith(("?", ":", "&&", "||", "+"))


def scan_source(name: str, text: str) -> list[Binding]:
    found = []
    for match in BINDING.finditer(text):
        end = _value_end(text, match.end())
        expression = " ".join(re.sub(r"//[^\n]*", "", text[match.end() : end]).split())
        prop = match.group(1)
        prop = prop.split()[-1]
        line = text.count("\n", 0, match.start(1)) + 1
        found.append(Binding(name, line, prop, expression))
    return found


def scan_directory(directory: Path = QML_DIR) -> list[Binding]:
    found: list[Binding] = []
    for path in sorted(directory.glob("*.qml")):
        found.extend(scan_source(path.name, path.read_text()))
    return found


def _leaf_colour(kind: str, parts: tuple[str, ...], scheme: dict[str, Rgb], bg: Rgb) -> Rgb | None:
    """The colour of one leaf over ``bg`` (None: a fill or transparent, nothing to check)."""
    if kind == "role":
        return scheme[FOREGROUND_ROLES[parts[0]]]
    if kind == "alpha":
        return blend(scheme[FOREGROUND_ROLES[parts[0]]], bg, float(parts[1]))
    if kind == "tint":
        base, front = (scheme[FOREGROUND_ROLES[role]] for role in parts[:2])
        return tint(base, front, float(parts[2]))
    if kind == "hex":
        digits = parts[0] if len(parts[0]) == 6 else "".join(c * 2 for c in parts[0])
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
    return NAMED[parts[0]]


def _leaves(expression: str) -> tuple[list[tuple[str, tuple[str, ...]]], str]:
    """The colour leaves of ``expression`` and what is left once they are taken out."""
    leaves: list[tuple[str, tuple[str, ...]]] = []
    rest = expression
    for kind, pattern in (("tint", TINT), ("alpha", ALPHA), ("role", ROLE), ("hex", HEX)):
        for match in pattern.finditer(rest):
            leaves.append((kind, match.groups()))
        rest = pattern.sub(" ", rest)
    for match in WORD.finditer(rest):
        word = match.group(0)[1:-1].lower()
        if word in NAMED:
            leaves.append(("name", (word,)))
            rest = rest.replace(match.group(0), " ")
    return leaves, rest


def _bad_roles(leaves: list[tuple[str, tuple[str, ...]]]) -> list[str]:
    """Theme roles the scan does not know (a fill role is fine only as a plain leaf)."""
    problems = []
    for kind, parts in leaves:
        if kind not in ("role", "alpha", "tint"):
            continue
        roles = parts[:2] if kind == "tint" else parts[:1]
        known = FOREGROUND_ROLES.keys() | (FILL_ROLES if kind == "role" else set())
        problems.extend(f"unknown theme role {role}" for role in roles if role not in known)
    return problems


def _check_binding(binding: Binding) -> list[str]:
    where = f"{binding.file}:{binding.line}: {binding.prop}: {binding.expression}"
    if (binding.file, binding.expression) in ALLOWED:
        return []
    if "palette" in binding.prop:
        return [f"{where} -- palette bindings are not supported (allow-list it with a reason)"]
    leaves, rest = _leaves(binding.expression)
    if not leaves:
        return [f"{where} -- no colour the scan understands"]
    rest = COMPARISON.sub(" ", rest)  # strings a condition compares with are not colours
    if LEFTOVER.search(rest) or WORD.search(rest):
        return [f"{where} -- unsupported colour source ({rest.strip()[:60]})"]
    unknown = _bad_roles(leaves)
    if unknown:
        return [f"{where} -- {unknown[0]}"]
    is_line = binding.prop.endswith(".color") and "border" in binding.prop
    minimum = NON_TEXT_MINIMUM if is_line else TEXT_MINIMUM
    out = []
    for scheme_name, scheme in SCHEMES.items():
        for bg_name in BACKGROUNDS:
            for kind, parts in leaves:
                if kind == "role" and parts[0] in FILL_ROLES:
                    continue
                colour = _leaf_colour(kind, parts, scheme, scheme[bg_name])
                if colour is None:
                    continue
                ratio = contrast(colour, scheme[bg_name])
                if ratio < minimum:
                    out.append(f"{where} -- {ratio:.2f}:1 on {scheme_name} {bg_name} (< {minimum})")
    return out


def check_source(name: str, text: str) -> list[str]:
    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        if JS_ASSIGN.search(re.sub(r"//.*", "", line)):
            problems.append(f"{name}:{number}: colour set from JavaScript: {line.strip()}")
    for binding in scan_source(name, text):
        problems.extend(_check_binding(binding))
    return problems


def check_directory(directory: Path = QML_DIR) -> list[str]:
    problems = []
    for path in sorted(directory.glob("*.qml")):
        problems.extend(check_source(path.name, path.read_text()))
    return problems
