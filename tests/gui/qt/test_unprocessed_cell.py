"""A photo saved whole shows in the results grid with a visible "Not processed" label."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QUrl

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


def checked_then_scripted(out: Path, release: threading.Event):
    """The scan above, preceded by a scanner check that runs long (CHECKING, then WAITING)."""
    scan = scripted_scan(out)

    def session(request: Any, **hooks: Any) -> SessionResult:
        hooks["on_stage"](Stage.CHECKING)
        hooks["on_stage"](Stage.WAITING)
        release.wait(timeout=10)
        return scan(request, **hooks)

    return session


def test_a_slow_scanner_check_and_a_sheet_saved_whole_show_in_the_same_run(
    make_bridge: Any, open_window: Any, messages: list[str], out: Path
) -> None:
    release = threading.Event()
    bridge = make_bridge(session=checked_then_scripted(out, release))
    window, warnings = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.progressText == "Checking the scanner…", "the check to be shown")
    settle()  # the WAITING stage that follows changes neither the state nor the text
    assert bridge.state == "scanning"
    assert bridge.progressText == "Checking the scanner…"
    assert bridge.bannerText == ""
    release.set()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    assert bridge.progressText == ""
    assert bridge.bannerKind == "warning"
    assert "1 photo needs checking" in bridge.bannerText
    assert "Photo 2 of 3 fed" in bridge.bannerText
    assert child(window, "photosHeading").property("text") == "Photos (2), 1 photo needs checking"
    assert warnings == []
    assert messages == []


def lone_back_scan(out: Path):
    """A session whose sheet 1 has only its back readable and sheet 2 a front and a back."""
    folder = out / ALBUM

    def pages(index: int, *, front: bool) -> WrittenFiles:
        stem = folder / f"{ALBUM}_{index:04d}_unprocessed"
        return WrittenFiles(
            directory=folder,
            index=index,
            original=stem.with_suffix(".jpg") if front else None,
            enhanced=None,
            back=folder / f"{stem.name}_b.jpg",
            unprocessed_reason=REASON,
        )

    def session(request: Any, **hooks: Any) -> SessionResult:
        hooks["on_stage"](Stage.PROCESSING)
        lone, both = (with_images(pages(1, front=False)), with_images(pages(2, front=True)))
        for files in (lone, both):
            hooks["on_photo"](files)
        hooks["on_stage"](Stage.DONE)
        failed = tuple(
            SheetIssue(n, (f"page-{n:04d}.png",), REASON, f) for n, f in ((1, lone), (2, both))
        )
        return SessionResult(
            process=ProcessResult(failed=failed, sheets=2),
            pages_scanned=4,
            raw_dir=out / ".raw" / "stamp",
            raw_reason=RawReason.SHEETS_FAILED,
        )

    return session


def test_a_lone_back_is_shown_once_and_labelled_as_the_back(
    make_bridge: Any, open_window: Any, messages: list[str], out: Path
) -> None:
    bridge = make_bridge(session=lone_back_scan(out))
    window, warnings = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    grid = child(window, "photosGrid")
    wait_until(lambda: len(cells_of(grid)) == 2, "the cells")
    lone, both = cells_of(grid)
    back = QUrl.fromLocalFile(str(out / ALBUM / f"{ALBUM}_0001_unprocessed_b.jpg")).toString()
    (picture,) = named_items(lone, "frontImage")
    assert picture.property("source").toString() == back
    (thumbnail,) = named_items(lone, "backImage")
    assert thumbnail.property("visible") is False  # the same picture is not shown a second time
    (label,) = named_items(lone, "backOnlyLabel")
    assert label.property("visible") is True
    assert label.property("text") == "Back page"
    (thumbnail,) = named_items(both, "backImage")
    assert thumbnail.property("visible") is True  # a front with its back keeps its thumbnail
    (label,) = named_items(both, "backOnlyLabel")
    assert label.property("visible") is False
    settle()
    assert warnings == []
    assert messages == []
