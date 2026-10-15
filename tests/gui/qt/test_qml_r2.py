"""Review round 2 in the window: the words of the offers and the pictures' fit."""

from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtQml import QQmlEngine, QQmlExpression

from tests.gui.helpers import ScriptedSession
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, invoke, settle, wait_until
from tests.gui.qt.test_qml import cells_of, named_items, ready

pytestmark = pytest.mark.usefixtures("kirigami")
open_window = test_qml.open_window  # the fixture that opens the window
PRESERVE_ASPECT_FIT = 1  # QtQuick Image.PreserveAspectFit


def fill_mode(image: Any) -> int:
    """An Image's fillMode (PySide cannot convert the enum through ``property()``)."""
    context = QQmlEngine.contextForObject(image)
    value, failed = QQmlExpression(context, image, "fillMode").evaluate()
    assert not failed
    return int(value)


def test_every_picture_of_a_photo_cell_is_fitted_not_stretched_as_loaded(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()  # the first photo has a back
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    grid = child(window, "photosGrid")
    wait_until(lambda: len(cells_of(grid)) == 3, "the cells")
    cells = cells_of(grid)
    fronts = [i for cell in cells for i in named_items(cell, "frontImage")]
    backs = [i for cell in cells for i in named_items(cell, "backImage")]
    assert len(fronts) == 3
    assert len(backs) == 3  # present in every cell (hidden when there is no back)
    assert {fill_mode(i) for i in fronts + backs} == {PRESERVE_ASPECT_FIT}


def test_the_close_question_names_what_is_running(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_bridge(session=ScriptedSession(out, hold=True))
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    window.close()
    dialog = child(window, "cancelDialog")
    wait_until(lambda: dialog.property("visible") is True, "the question")
    assert bridge.closeTitle
    assert dialog.property("title") == bridge.closeTitle
    assert dialog.property("subtitle") == bridge.closeText
    invoke(dialog, "reject")


def test_the_button_that_processes_kept_pages_says_where_they_go(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_bridge(session=ScriptedSession(out, hold=True))
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.canProcessKept, "the offer")
    button = child(window, "processKeptButton")
    assert str(out) in bridge.processKeptText
    assert button.property("text") == bridge.processKeptText
