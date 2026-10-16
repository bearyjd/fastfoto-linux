"""The results banner counts the photos saved whole and says which sheet each was."""

from pathlib import Path

from fastfoto_linux.gui.photos import item_from_files
from fastfoto_linux.gui.report import photos_heading, result_banner
from fastfoto_linux.gui.state import State
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import ProcessResult, SheetIssue
from fastfoto_linux.session import RawReason, SessionResult
from tests.gui.helpers import written

OUT = Path("/srv/demo/FastFoto/Family Trips")
RAW = Path("/srv/demo/FastFoto/.raw/20261015T020000Z")
REASON = "the photo's edges were not found (two items fed together?)"


def whole_page(index: int, *, back: bool = False) -> WrittenFiles:
    stem = OUT / f"Family Trips_{index:04d}_unprocessed"
    return WrittenFiles(
        directory=OUT,
        index=index,
        original=stem.with_suffix(".jpg"),
        enhanced=None,
        back=OUT / f"{stem.name}_b.jpg" if back else None,
        unprocessed_reason=REASON,
    )


def issue(sheet: int, saved: WrittenFiles | None) -> SheetIssue:
    return SheetIssue(sheet, (f"page-{2 * sheet - 1:04d}.png",), REASON, saved)


def banner_for(process: ProcessResult):
    result = SessionResult(
        process=process, pages_scanned=6, raw_dir=RAW, raw_reason=RawReason.SHEETS_FAILED
    )
    banner = result_banner(State.DONE, result)
    assert banner is not None
    return banner


def test_one_photo_saved_whole_is_counted_as_needing_a_check() -> None:
    banner = banner_for(
        ProcessResult(
            written=(written(OUT, 1), written(OUT, 3)),
            failed=(issue(2, whole_page(2)),),
            sheets=3,
        )
    )
    assert banner.kind == "warning"
    assert "1 photo needs checking" in banner.text
    assert "2 photos saved" in banner.text
    assert "sheet could not be processed" not in banner.text
    assert str(RAW) in banner.text


def test_the_banner_names_the_sheet_in_feed_order_the_reason_and_the_file() -> None:
    banner = banner_for(
        ProcessResult(written=(written(OUT, 1),), failed=(issue(2, whole_page(2)),), sheets=3)
    )
    assert (
        f"Photo 2 of 3 fed: {REASON} — whole page saved as Family Trips_0002_unprocessed.jpg"
    ) in banner.text
    assert "top" not in banner.text.lower().split()
    assert "bottom" not in banner.text.lower().split()


def test_a_saved_back_is_named_too() -> None:
    banner = banner_for(
        ProcessResult(failed=(issue(2, whole_page(2, back=True)),), sheets=3, written=())
    )
    assert (
        "whole pages saved as Family Trips_0002_unprocessed.jpg and "
        "Family Trips_0002_unprocessed_b.jpg"
    ) in banner.text


def test_several_photos_saved_whole_are_counted_in_the_plural() -> None:
    banner = banner_for(
        ProcessResult(
            written=(written(OUT, 2),),
            failed=(issue(1, whole_page(1)), issue(3, whole_page(3))),
            sheets=3,
        )
    )
    assert "2 photos need checking" in banner.text


def test_only_photos_saved_whole_are_not_reported_as_no_photos_found() -> None:
    banner = banner_for(ProcessResult(failed=(issue(1, whole_page(1)),), sheets=1))
    assert "No photos were found" not in banner.text
    assert "1 photo needs checking" in banner.text


def test_a_sheet_that_could_not_be_saved_at_all_is_still_a_lost_sheet() -> None:
    banner = banner_for(
        ProcessResult(
            written=(written(OUT, 1),),
            failed=(issue(2, whole_page(2)), issue(3, None)),
            sheets=3,
        )
    )
    assert "1 sheet could not be processed" in banner.text
    assert "1 photo needs checking" in banner.text


def test_an_item_of_a_whole_page_carries_the_reason_and_the_file() -> None:
    item = item_from_files(whole_page(4, back=True))
    assert item.unprocessed_reason == REASON
    assert item.unprocessed is True
    assert item.title == "Family Trips_0004_unprocessed"
    assert item.front == OUT / "Family Trips_0004_unprocessed.jpg"
    assert item.back == OUT / "Family Trips_0004_unprocessed_b.jpg"


def test_an_item_of_a_normal_photo_is_not_flagged() -> None:
    item = item_from_files(written(OUT, 4))
    assert item.unprocessed is False
    assert item.unprocessed_reason is None


def test_a_cancelled_run_counts_the_photos_saved_whole_too() -> None:
    process = ProcessResult(
        written=(written(OUT, 1),), failed=(issue(2, whole_page(2)),), sheets=3, cancelled=True
    )
    result = SessionResult(
        process=process,
        pages_scanned=4,
        raw_dir=RAW,
        raw_reason=RawReason.CANCELLED,
        cancelled=True,
    )
    banner = result_banner(State.CANCELLED, result)
    assert banner is not None
    assert "Cancelled. 1 photo was saved. 1 photo needs checking." in banner.text
    assert str(RAW) in banner.text


# --- many failed sheets: one line per kind ------------------------------------------------------


def several(numbers: list[int], *, lost: tuple[int, ...] = (), sheets: int = 10) -> ProcessResult:
    failed = [issue(n, whole_page(n)) for n in numbers] + [issue(n, None) for n in lost]
    return ProcessResult(written=(written(OUT, 1),), failed=tuple(failed), sheets=sheets)


def test_up_to_three_sheets_saved_whole_each_get_a_line() -> None:
    banner = banner_for(several([2, 5, 7]))
    assert banner.text.count("whole page saved as") == 3
    assert "Photo 5 of 10 fed" in banner.text


def test_more_than_three_sheets_saved_whole_are_one_line_with_their_feed_numbers() -> None:
    banner = banner_for(several([2, 5, 7, 9]))
    assert "4 photos need checking: photos 2, 5, 7, 9 fed." in banner.text
    assert "whole page saved as" not in banner.text
    assert "1 photo saved." in banner.text
    assert len(banner.text.splitlines()) <= 2


def test_lost_sheets_are_listed_by_feed_number_when_there_are_many() -> None:
    banner = banner_for(several([2, 5], lost=(6, 8)))
    assert "2 sheets could not be processed: photos 6, 8 fed." in banner.text
    assert "2 photos need checking: photos 2, 5 fed." in banner.text
    assert "whole page saved as" not in banner.text


def test_the_rest_of_the_banner_is_unchanged_when_the_lines_collapse() -> None:
    banner = banner_for(several([2, 5, 7, 9]))
    assert banner.kind == "warning"
    assert str(RAW) in banner.text


# --- the results grid's heading says it the banner's way -----------------------------------------


def test_the_heading_counts_photos_and_the_ones_needing_a_check_separately() -> None:
    assert photos_heading(0, 0) == "Photos"
    assert photos_heading(3, 0) == "Photos (3)"
    assert photos_heading(3, 1) == "Photos (2), 1 photo needs checking"
    assert photos_heading(4, 2) == "Photos (2), 2 photos need checking"
    assert photos_heading(1, 1) == "Photos (0), 1 photo needs checking"
