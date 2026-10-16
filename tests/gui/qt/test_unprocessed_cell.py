"""A photo saved whole shows in the results grid with a visible "Not processed" label."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import ProcessResult, SheetIssue
from fastfoto_linux.session import RawReason, SessionResult, Stage
from tests.gui.helpers import ALBUM, with_images, written
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, settle, wait_until
from tests.gui.qt.test_qml import cells_of, named_items, ready

pytestmark = pytest.mark.usefixtures("kirigami")
open_window = test_qml.open_window  # the fixture that opens the window
REASON = "the photo's edges were not found (two items fed together?)"


def whole_page(directory: Path, index: int) -> WrittenFiles:
    stem = directory / f"{ALBUM}_{index:04d}_unprocessed"
    return WrittenFiles(
        directory=directory,
        index=index,
        original=stem.with_suffix(".jpg"),
        enhanced=None,
        back=None,
        unprocessed_reason=REASON,
    )


def scripted_scan(out: Path):
    """A session that saves sheets 1 and 3 as photos and sheet 2 as a whole page."""
    folder = out / ALBUM

    def session(request: Any, **hooks: Any) -> SessionResult:
        hooks["on_stage"](Stage.SCANNING)
        for number in range(1, 7):
            hooks["on_page"](number)
        hooks["on_stage"](Stage.PROCESSING)
        good = [with_images(replace(written(folder, n), enhanced=None)) for n in (1, 3)]
        bad = with_images(whole_page(folder, 2))
        for files in (good[0], bad, good[1]):
            hooks["on_photo"](files)
        hooks["on_stage"](Stage.DONE)
        failed = SheetIssue(2, ("page-0003.png", "page-0004.png"), REASON, bad)
        process = ProcessResult(written=tuple(good), failed=(failed,), sheets=3)
        return SessionResult(
            process=process,
            pages_scanned=6,
            raw_dir=out / ".raw" / "stamp",
            raw_reason=RawReason.SHEETS_FAILED,
        )

    return session


def test_only_the_whole_page_has_the_label_and_the_reason(
    make_bridge: Any, open_window: Any, messages: list[str], out: Path
) -> None:
    bridge = make_bridge(session=scripted_scan(out))
    window, warnings = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    grid = child(window, "photosGrid")
    wait_until(lambda: len(cells_of(grid)) == 3, "the cells")
    labels = [
        [i for i in named_items(cell, "notProcessedLabel") if i.property("visible")]
        for cell in cells_of(grid)
    ]
    assert [len(found) for found in labels] == [0, 1, 0]
    assert labels[1][0].property("text") == "Not processed"
    reasons = [i for cell in cells_of(grid) for i in named_items(cell, "reasonLabel")]
    assert [i.property("text") for i in reasons if i.property("visible")] == [REASON]
    settle()
    assert warnings == []
    assert messages == []


def test_the_banner_counts_the_photo_that_needs_checking(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_bridge(session=scripted_scan(out))
    open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    assert bridge.photoCount == 3
    assert "1 photo needs checking" in bridge.bannerText
    assert "Photo 2 of 3 fed" in bridge.bannerText


def test_the_heading_counts_photos_and_the_one_needing_a_check_separately(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_bridge(session=scripted_scan(out))
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    assert bridge.photosHeading == "Photos (2), 1 photo needs checking"
    heading = child(window, "photosHeading")
    assert heading.property("text") == "Photos (2), 1 photo needs checking"
