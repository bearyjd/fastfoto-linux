"""What assistive technology sees of the real window: names, roles, states, focus order.

The checks read the accessibility tree Qt builds from the QML (``QAccessible``), the same tree
Orca reads over AT-SPI, so a control without a name or a missing description fails here.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PIL import Image
from PySide6.QtCore import QMetaObject, QObject, QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQml import QJSValue, QQmlComponent, QQmlEngine, QQmlExpression, qmlContext

from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, settle
from tests.gui.qt.test_photo_edit_view import open_editor
from tests.gui.qt.test_qml_review_window import review_window  # noqa: F401  (a fixture)

pytestmark = pytest.mark.usefixtures("kirigami", "accessibility_on")
open_window = test_qml.open_window

ROLE = QAccessible.Role
# Everything a person can operate, or that reports a status: each needs a name.
NAMED_ROLES = {
    ROLE.Button,
    ROLE.ButtonMenu,
    ROLE.CheckBox,
    ROLE.ComboBox,
    ROLE.EditableText,
    ROLE.Indicator,
    ROLE.List,
    ROLE.PageTab,
    ROLE.ProgressBar,
    ROLE.RadioButton,
    ROLE.Slider,
    ROLE.SpinBox,
    ROLE.AlertMessage,
}
# Controls that appear only in some states (so they are not in the first sweep's visible set):
# the sweep must still find them in the tree and they must be named.
LATE_CONTROLS = {
    "errorBanner",
    "keptBanner",
    "resultBanner",
    "docLanguageProgressBar",
    "busyIndicator",
}
QML = Path(__file__).resolve().parents[3] / "src/fastfoto_linux/gui/qml"


@pytest.fixture
def accessibility_on() -> Iterator[None]:
    """Qt builds the accessibility tree only while it is active; do not leak that to other tests."""
    QAccessible.setActive(True)
    yield
    QAccessible.setActive(False)


COLLECT_NAMES = """(function collect(item, names) {
    for (let i = 0; i < item.children.length; i++) {
        const kid = item.children[i];
        if (kid.objectName !== "") names.push(kid.objectName);
        collect(kid, names);
    }
    return names;
})"""


def evaluate(item: Any, source: str) -> Any:
    """Run a JavaScript expression in the QML context of ``item``."""
    expression = QQmlExpression(qmlContext(item), item, source)
    value, failed = expression.evaluate()
    assert not failed and not expression.hasError(), expression.error().toString()
    return value.toVariant() if isinstance(value, QJSValue) else value


def named_objects(window: Any) -> dict[str, tuple[Any, Any]]:
    """Every app-authored (objectName'd) item with an accessible interface, visible or not.

    The names are collected in QML: walking the tree with ``childItems()`` would make PySide
    wrap the anonymous ``QQuickItem_QML_<n>`` types, and its type cache aborts the process on
    a name reused by an earlier test's engine.
    """
    names = evaluate(window.contentItem(), f"{COLLECT_NAMES}(this, [])")
    found: dict[str, tuple[Any, Any]] = {}
    for name in dict.fromkeys(names):
        item = window.findChild(QObject, name)  # list delegates are not QObject children
        iface = QAccessible.queryAccessibleInterface(item) if item is not None else None
        if iface is not None:
            found[name] = (item, iface)
    return found


def tree(iface: Any) -> Iterator[Any]:
    """Every accessible interface under ``iface``: each delegate instance of every list."""
    yield iface
    for index in range(iface.childCount()):
        kid = iface.child(index)
        if kid is not None:
            yield from tree(kid)


def unnamed(window: Any) -> list[str]:
    """Operable or status controls with no readable name, in every instance on every page.

    A name needs a letter or digit: an arrow glyph is the text of a button, not its name.
    Kirigami's own parts are skipped: the text parts inside a label or a combo box, and the
    hidden action button of a placeholder message.
    """
    found = []
    for iface in tree(QAccessible.queryAccessibleInterface(window)):
        if iface.role() not in NAMED_ROLES:
            continue
        if any(ch.isalnum() for ch in iface.text(QAccessible.Text.Name)):
            continue
        obj = iface.object()
        kind = obj.metaObject().className()
        if kind.startswith(("QQuickTextEdit", "QQuickTextField")):
            continue
        if iface.role() == ROLE.Button and iface.state().invisible and not obj.objectName():
            continue
        found.append(f"{obj.objectName() or kind} ({iface.role().name})")
    return found


def test_every_control_of_the_scan_page_has_an_accessible_name(
    make_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_bridge())
    settle()
    assert named_objects(window).keys() >= LATE_CONTROLS
    assert unnamed(window) == []


def test_every_control_of_the_settings_page_has_an_accessible_name(
    make_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_bridge())
    assert QMetaObject.invokeMethod(window, "openSettings")
    settle()
    assert "powerApplyButton" in named_objects(window)
    assert unnamed(window) == []


def test_every_control_of_the_page_review_has_an_accessible_name(review_window: Any) -> None:  # noqa: F811
    window = review_window[0]
    assert "reviewSaveButton" in named_objects(window)
    assert unnamed(window) == []


def test_every_control_of_the_photo_editor_has_an_accessible_name(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge, _view, _worker = open_editor(make_bridge, out)
    window, _ = open_window(bridge)
    settle()
    assert "photoSaveCopy" in named_objects(window)
    assert unnamed(window) == []


def test_a_disabled_scan_button_says_why_it_is_disabled(make_bridge: Any, open_window: Any) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    settle()
    assert not bridge.canScan and bridge.whyNotScan
    _item, iface = named_objects(window)["scanButton"]
    assert iface.text(QAccessible.Text.Description) == bridge.whyNotScan


def test_the_scanner_chip_describes_the_scanner_state_in_words(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    settle()
    _item, iface = named_objects(window)["scannerChip"]
    assert iface.text(QAccessible.Text.Description) == bridge.scannerText


def test_the_selected_review_page_is_exposed_as_selected(review_window: Any) -> None:  # noqa: F811
    window = review_window[0]
    grid = child(window, "reviewGrid")
    states = []
    for index in range(3):
        cell = _cell(grid, index)
        iface = QAccessible.queryAccessibleInterface(cell)
        states.append(iface.state().selected)
    assert states.count(True) == 1 and states[grid.property("currentIndex")]


def _cell(grid: Any, index: int) -> Any:
    from PySide6.QtCore import Q_ARG, Q_RETURN_ARG
    from PySide6.QtQuick import QQuickItem

    cell = QMetaObject.invokeMethod(
        grid, "itemAtIndex", Q_RETURN_ARG(QQuickItem), Q_ARG(int, index)
    )
    assert cell is not None
    return cell


def focus_chain(start: Any) -> list[str]:
    """Names of the app-authored items Tab visits from ``start``, once round."""
    names: list[str] = []
    seen: set[int] = set()
    item = start.nextItemInFocusChain(True)
    while item is not None and id(item) not in seen:
        seen.add(id(item))
        if item.objectName():
            names.append(item.objectName())
        item = item.nextItemInFocusChain(True)
    return names


def assert_in_order(chain: list[str], expected: list[str]) -> None:
    """``expected`` appears in ``chain`` in that order (Kirigami's own items may sit between)."""
    position = -1
    for name in expected:
        assert name in chain[position + 1 :], f"{name} is not after {chain[position]} in {chain}"
        position = chain.index(name, position + 1)


def test_tab_goes_through_the_photo_form_in_reading_order_to_the_results(
    make_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_bridge())
    settle()
    chain = focus_chain(child(window, "photosModeButton"))
    assert_in_order(
        chain,
        [
            "documentsModeButton",
            "folderField",
            "chooseFolderButton",
            "albumField",
            "dateField",
            "notesField",
            "feedBox",
            "backsBox",
            "dpiBox",
            "presetBox",
            "orientBox",
            "restoreBox",
            "redeyeBox",
            "keepOriginalBox",
            "enhancedSwitch",
            "photosGrid",
            "scannerChip",
            "checkAgainButton",
        ],
    )


def test_tab_goes_through_the_review_page_from_the_pages_to_save(review_window: Any) -> None:  # noqa: F811
    window = review_window[0]
    assert "reviewGrid" in focus_chain(child(window, "reviewBackButton")), "Tab reaches the pages"
    chain = focus_chain(child(window, "reviewGrid"))
    assert_in_order(chain, ["reviewBackButton", "reviewSaveButton"])


def test_every_enabled_visible_control_can_be_reached_with_tab(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    bridge.checkScanner()
    settle()
    reached = set(focus_chain(child(window, "photosModeButton")))
    operable = {ROLE.Button, ROLE.CheckBox, ROLE.ComboBox, ROLE.EditableText, ROLE.List}
    missing = sorted(
        name
        for name, (item, iface) in named_objects(window).items()
        if iface.role() in operable
        and item.isVisible()
        and item.isEnabled()
        and name not in reached
        # the other mode's form and the page behind are not on this page's chain
        and not name.startswith(("doc", "review", "photo", "power", "document"))
    )
    assert missing == []


GLYPHS = """(function glyphs(item, root, found) {
    for (let i = 0; i < item.children.length; i++) {
        const kid = item.children[i];
        if (kid.objectName === "photoEyeMarkerGlyph") {
            const a = kid.mapToItem(root, 0, 0);
            const b = kid.mapToItem(root, kid.width, kid.height);
            found.push({text: kid.text, x0: Math.min(a.x, b.x), y0: Math.min(a.y, b.y),
                        x1: Math.max(a.x, b.x), y1: Math.max(a.y, b.y),
                        point: kid.font.pointSize, pixel: kid.font.pixelSize});
        }
        glyphs(kid, root, found);
    }
    return found;
})"""
CANVAS = (200, 100)


def eye_marker_glyphs(rois: list[tuple[bool, list[int]]], out: Path) -> list[dict[str, Any]]:
    """Status symbol, text size and place (in canvas coordinates) of each eye marker drawn."""
    image = out / "marker-preview.png"
    Image.new("RGB", CANVAS, (90, 90, 90)).save(image)
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "PhotoEditCanvas.qml")))
    assert component.isReady(), [error.toString() for error in component.errors()]
    candidates = [
        {"id": f"eye{n}", "accepted": accepted, "roi": roi}
        for n, (accepted, roi) in enumerate(rois)
    ]
    canvas = component.createWithInitialProperties(
        dict(
            width=float(CANVAS[0]),
            height=float(CANVAS[1]),
            imageUrl=QUrl.fromLocalFile(str(image)).toString(),
            sourceWidth=CANVAS[0],
            sourceHeight=CANVAS[1],
            candidates=candidates,
            selectedId="",
        )
    )
    assert canvas is not None
    try:
        settle()
        return list(evaluate(canvas, f"{GLYPHS}(this, this, [])"))
    finally:
        canvas.deleteLater()
        engine.deleteLater()
        settle()


MIDDLE = [20, 40, 40, 60]


def test_an_eye_marker_says_accepted_or_rejected_by_a_symbol_not_only_by_colour(
    out: Path,
) -> None:
    glyphs = eye_marker_glyphs([(True, MIDDLE), (False, [60, 40, 80, 60])], out)
    texts = [g["text"] for g in glyphs]
    assert len(texts) == 2 and texts[0] != texts[1] and all(texts)


@pytest.mark.parametrize(
    "roi", [[20, 0, 40, 8], [20, 92, 40, 100], [0, 40, 8, 60], [192, 40, 200, 60]]
)
def test_the_marker_symbol_stays_inside_the_canvas_for_a_marker_at_any_edge(
    roi: list[int], out: Path
) -> None:
    """The canvas clips: a symbol above a top-edge marker would be cut off."""
    (glyph,) = eye_marker_glyphs([(True, roi)], out)
    assert glyph["x0"] >= 0 and glyph["x1"] <= CANVAS[0], glyph
    assert glyph["y0"] >= 0 and glyph["y1"] <= CANVAS[1], glyph


def test_the_marker_symbol_follows_the_system_font_size(out: Path) -> None:
    from PySide6.QtGui import QFont, QGuiApplication

    original = QGuiApplication.font()
    big = QFont(original)
    big.setPointSizeF(original.pointSizeF() * 2)
    try:
        QGuiApplication.setFont(big)
        (glyph,) = eye_marker_glyphs([(True, MIDDLE)], out)
    finally:
        QGuiApplication.setFont(original)
    assert glyph["point"] == pytest.approx(big.pointSizeF())
    (normal,) = eye_marker_glyphs([(True, MIDDLE)], out)
    assert normal["point"] == pytest.approx(original.pointSizeF())


def test_qt_tint_is_the_per_channel_blend_the_contrast_test_computes(
    make_bridge: Any, open_window: Any
) -> None:
    """The contrast test mirrors ``Qt.tint`` in Python; check it on the real one."""
    from tests.gui.qml_colours import tint

    window, _ = open_window(make_bridge())
    settle()
    button = child(window, "scanButton")
    value = evaluate(
        button,
        "Qt.tint(Qt.rgba(218/255, 68/255, 83/255, 1),"
        " Qt.alpha(Qt.rgba(35/255, 38/255, 41/255, 1), 0.3))",
    )
    got = (value.red(), value.green(), value.blue())
    assert got == pytest.approx(tint((218, 68, 83), (35, 38, 41), 0.3), abs=1.01)
