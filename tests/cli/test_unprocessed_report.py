"""``ffscan`` names the sheet that was saved whole, in feed order, and exits 1."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.cli.summary import print_summary
from fastfoto_linux.output import WrittenFiles
from fastfoto_linux.pipeline.process import ProcessResult, SheetIssue
from fastfoto_linux.session import raw as rawdir
from tests._output_helpers import names
from tests.process_helpers import NO_PHOTO_REASON, plain_sheet, wide_sheet, write_sheets

FAST = ["--no-orient", "--no-restore"]
FOLDER = Path("/srv/demo/Test")
STAMP = "20261013T230000Z"


@pytest.fixture(autouse=True)
def fixed_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)


def whole_page(index: int = 4, *, back: bool = False) -> WrittenFiles:
    stem = FOLDER / f"Test_{index:04d}_unprocessed"
    return WrittenFiles(
        directory=FOLDER,
        index=index,
        original=stem.with_suffix(".jpg"),
        enhanced=None,
        back=FOLDER / f"{stem.name}_b.jpg" if back else None,
        unprocessed_reason=NO_PHOTO_REASON,
    )


def failed_sheet(saved: WrittenFiles | None, sheet: int = 4) -> SheetIssue:
    return SheetIssue(sheet, ("page-0007.png", "page-0008.png"), NO_PHOTO_REASON, saved)


def summary_of(result: ProcessResult, capsys) -> tuple[str, str]:
    print_summary(result)
    captured = capsys.readouterr()
    return captured.out, captured.err


def test_the_summary_says_which_photo_of_the_batch_was_saved_whole(capsys) -> None:
    result = ProcessResult(failed=(failed_sheet(whole_page()),), sheets=6)
    _, err = summary_of(result, capsys)
    assert (
        f"photo 4 of 6 fed: {NO_PHOTO_REASON} — whole page saved as Test_0004_unprocessed.jpg"
    ) in err


def test_a_saved_back_is_named_too(capsys) -> None:
    result = ProcessResult(failed=(failed_sheet(whole_page(back=True)),), sheets=6)
    _, err = summary_of(result, capsys)
    assert "whole pages saved as Test_0004_unprocessed.jpg and Test_0004_unprocessed_b.jpg" in err


def test_the_summary_does_not_claim_a_position_in_the_stack(capsys) -> None:
    result = ProcessResult(failed=(failed_sheet(whole_page()),), sheets=6)
    out, err = summary_of(result, capsys)
    text = (out + err).lower()
    assert "top" not in text
    assert "bottom" not in text


def test_the_folder_of_a_batch_saved_whole_is_still_listed(capsys) -> None:
    result = ProcessResult(failed=(failed_sheet(whole_page()),), sheets=6)
    out, _ = summary_of(result, capsys)
    assert f"output: {FOLDER}" in out


def test_a_sheet_that_could_not_be_saved_whole_is_listed_with_its_pages_and_reason(capsys) -> None:
    result = ProcessResult(failed=(failed_sheet(None),), sheets=6)
    _, err = summary_of(result, capsys)
    assert "photo 4 of 6 fed (page-0007.png, page-0008.png)" in err
    assert NO_PHOTO_REASON in err


def test_ffscan_process_saves_the_sheet_whole_names_it_and_exits_1(tmp_path, out, capsys) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet(0), wide_sheet(1), plain_sheet(2)])
    code = main(["process", *map(str, pages), "--out", str(out), *FAST, "--backs", "never"])
    assert code == 1
    assert [n for n in names(out) if n.endswith(".jpg")] == [
        "FastFoto_0001.jpg",
        "FastFoto_0002_unprocessed.jpg",
        "FastFoto_0003.jpg",
    ]
    captured = capsys.readouterr()
    assert "photos written: 2" in captured.out
    assert (
        f"photo 2 of 3 fed: {NO_PHOTO_REASON} — whole page saved as FastFoto_0002_unprocessed.jpg"
    ) in captured.err


def test_ffscan_scan_does_the_same_and_still_says_where_the_raw_pages_are(
    out, transport, capsys
) -> None:
    transport.sheets = [plain_sheet(0), wide_sheet(1), plain_sheet(2)]
    code = main(["scan", "--out", str(out), *FAST, "--backs", "never", "--discard-raw"])
    assert code == 1
    assert "FastFoto_0002_unprocessed.jpg" in names(out)
    captured = capsys.readouterr()
    assert "photo 2 of 3 fed" in captured.err
    kept = out / ".raw" / STAMP
    assert f"raw pages kept in {kept}" in captured.err
    assert len(list(kept.iterdir())) == 6
