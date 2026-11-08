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
from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQml import QQmlComponent, QQmlEngine

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


def walk(item: Any) -> Iterator[Any]:
    yield item
    for kid in item.childItems():
        yield from walk(kid)


def named_objects(window: Any) -> dict[str, tuple[Any, Any]]:
    """Every app-authored (objectName'd) item with an accessible interface, visible or not."""
    found: dict[str, tuple[Any, Any]] = {}
    for item in walk(window.contentItem()):
        name = item.objectName()
        iface = QAccessible.queryAccessibleInterface(item) if name else None
        if iface is not None:
            found.setdefault(name, (item, iface))
    return found


def unnamed(window: Any) -> list[str]:
    return sorted(
        f"{name} ({iface.role().name})"
        for name, (_item, iface) in named_objects(window).items()
        if iface.role() in NAMED_ROLES and not iface.text(QAccessible.Text.Name).strip()
    )


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


def eye_markers(accepted_flags: tuple[bool, ...], out: Path) -> tuple[Any, Any, list[Any]]:
    image = out / "marker-preview.png"
    Image.new("RGB", (200, 100), (90, 90, 90)).save(image)
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "PhotoEditCanvas.qml")))
    assert component.isReady(), [error.toString() for error in component.errors()]
    candidates = [
        {"id": f"eye{n}", "accepted": flag, "roi": [20 + 40 * n, 20, 40 + 40 * n, 40]}
        for n, flag in enumerate(accepted_flags)
    ]
    canvas = component.createWithInitialProperties(
        dict(
            width=200.0,
            height=100.0,
            imageUrl=QUrl.fromLocalFile(str(image)).toString(),
            sourceWidth=200,
            sourceHeight=100,
            candidates=candidates,
            selectedId="",
        )
    )
    assert canvas is not None
    settle()
    markers = [i for i in walk(canvas) if i.objectName() == "photoEyeMarker"]
    return engine, canvas, markers


def test_an_eye_marker_says_accepted_or_rejected_by_a_symbol_not_only_by_colour(
    out: Path,
) -> None:
    engine, canvas, markers = eye_markers((True, False), out)
    try:
        glyphs = []
        for marker in markers:
            found = [i for i in walk(marker) if i.objectName() == "photoEyeMarkerGlyph"]
            assert len(found) == 1, "each marker carries one status symbol"
            glyphs.append(found[0].property("text"))
        assert len(glyphs) == 2 and glyphs[0] != glyphs[1] and all(glyphs)
    finally:
        canvas.deleteLater()
        engine.deleteLater()
        settle()


def test_qt_tint_is_the_per_channel_blend_the_contrast_test_computes(
    make_bridge: Any, open_window: Any
) -> None:
    """The contrast test mirrors ``Qt.tint`` in Python; check it on the real one."""
    from PySide6.QtQml import QQmlExpression, qmlContext

    from tests.gui.test_accessibility_contrast import tint

    window, _ = open_window(make_bridge())
    settle()
    button = child(window, "scanButton")
    expression = QQmlExpression(
        qmlContext(button),
        button,
        "Qt.tint(Qt.rgba(218/255, 68/255, 83/255, 1),"
        " Qt.alpha(Qt.rgba(35/255, 38/255, 41/255, 1), 0.3))",
    )
    value, failed = expression.evaluate()
    assert not failed and not expression.hasError(), expression.error().toString()
    got = (value.red(), value.green(), value.blue())
    assert got == pytest.approx(tint((218, 68, 83), (35, 38, 41), 0.3), abs=1.01)
