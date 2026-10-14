"""``ffscan process``: existing raw pages in, album files out."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from tests._output_helpers import names
from tests.cli.fakes import write_dummy_page
from tests.process_helpers import (
    BLANK,
    DPI,
    original_date,
    page_name,
    plain_sheet,
    write_front_pages,
    write_sheets,
    written_sheet,
)
from tests.synth import make_duplex_sheet

FAST = ["--no-orient", "--no-restore"]
NEAR_WHITE = (245, 245, 245)


def process(out: Path, pages, *extra: str) -> int:
    return main(["process", *map(str, pages), "--out", str(out), *FAST, *extra])


def test_pages_are_sorted_by_number_not_alphabetically(tmp_path, out, spy) -> None:
    files = {n: write_dummy_page(tmp_path / "raw", f"page-{n}.png") for n in (10, 2, 1)}
    assert process(out, [files[10], files[2], files[1]]) == 0
    ((pages, _),) = spy
    assert [p.name for p in pages] == ["page-1.png", "page-2.png", "page-10.png"]


def test_sheets_are_processed_and_summarised(tmp_path, out, capsys) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet(0), written_sheet(1)])
    assert process(out, pages, "--date", "1975-06-14") == 0
    assert names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg", "FastFoto_0002_b.jpg"]
    assert original_date(out / "FastFoto_0001.jpg") == "1975:06:14 00:00:00"
    stdout = capsys.readouterr().out
    assert "photos written: 2" in stdout
    assert "backs kept: 1" in stdout
    assert "enhanced: 0" in stdout


def test_the_default_chain_orients_and_restores_into_an_enhanced_copy(
    tmp_path, out, capsys
) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet()])
    assert main(["process", *map(str, pages), "--out", str(out)]) == 0
    assert names(out) == ["FastFoto_0001.jpg", "FastFoto_0001_a.jpg"]
    assert "enhanced: 1" in capsys.readouterr().out


def test_face_up_loading_reads_the_first_page_of_a_sheet_as_the_front(tmp_path, out) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet()], front_first=True)
    assert process(out, pages, "--feed", "face-up", "--backs", "always") == 0
    assert names(out) == ["FastFoto_0001.jpg", "FastFoto_0001_b.jpg"]


def test_simplex_pages_are_all_fronts(tmp_path, out) -> None:
    pages = write_front_pages(tmp_path / "raw", 3)
    assert process(out, pages, "--simplex") == 0
    assert names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg", "FastFoto_0003.jpg"]


def test_a_bad_sheet_is_exit_1_and_lists_its_pages_while_the_rest_is_written(
    tmp_path, out, capsys
) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet(0), plain_sheet(1), plain_sheet(2)])
    pages[2].write_bytes(b"not a png")
    assert process(out, pages) == 1
    assert names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]
    err = capsys.readouterr().err
    assert page_name(3) in err
    assert page_name(4) in err
    assert "Traceback" not in err


def test_uncertain_sheets_are_listed_in_the_summary(tmp_path, out, capsys) -> None:
    tie = make_duplex_sheet(dpi=DPI, front={"photo_rgb": NEAR_WHITE}, back=BLANK)
    pages = write_sheets(tmp_path / "raw", [plain_sheet(), tie])
    assert process(out, pages, "--backs", "never") == 0
    stdout = capsys.readouterr().out
    assert "told apart" in stdout
    assert page_name(3) in stdout
    assert page_name(1) not in stdout
    assert "FastFoto_0002_b.jpg" in names(out)


def test_a_missing_page_is_exit_2_and_nothing_runs(tmp_path, out, spy, capsys) -> None:
    present = write_dummy_page(tmp_path / "raw", "page-1.png")
    assert process(out, [present, tmp_path / "raw" / "page-2.png"]) == 2
    assert spy == []
    assert "page-2.png" in capsys.readouterr().err


def test_a_folder_is_not_a_page(tmp_path, out, spy) -> None:
    assert process(out, [tmp_path]) == 2
    assert spy == []


def test_pages_are_required(out, capsys) -> None:
    assert main(["process", "--out", str(out)]) == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_a_missing_output_folder_is_exit_2_and_mkdir_creates_it(tmp_path, spy, capsys) -> None:
    page = write_dummy_page(tmp_path / "raw", "page-1.png")
    target = tmp_path / "a" / "b"
    assert process(target, [page]) == 2
    assert "--mkdir" in capsys.readouterr().err
    assert spy == []
    assert process(target, [page], "--mkdir") == 0
    assert target.is_dir()


def test_an_output_path_that_is_a_file_is_exit_2(tmp_path, spy, capsys) -> None:
    page = write_dummy_page(tmp_path / "raw", "page-1.png")
    not_a_folder = write_dummy_page(tmp_path, "album")
    assert process(not_a_folder, [page], "--mkdir") == 2
    assert "not a folder" in capsys.readouterr().err
    assert spy == []


def test_an_output_folder_that_cannot_be_made_is_exit_1(tmp_path, spy, capsys) -> None:
    page = write_dummy_page(tmp_path / "raw", "page-1.png")
    blocker = write_dummy_page(tmp_path, "blocker")
    assert process(blocker / "album", [page], "--mkdir") == 1
    assert "cannot create" in capsys.readouterr().err
    assert spy == []


def test_backs_dropped_for_lack_of_writing_are_reported_with_their_pages(
    tmp_path, out, capsys
) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet(0), written_sheet(1), plain_sheet(2)])
    assert process(out, pages) == 0
    stdout = capsys.readouterr().out
    assert "backs dropped: 2 (no writing detected; use --backs always to keep them)" in stdout
    assert page_name(1) in stdout
    assert page_name(5) in stdout
    assert page_name(3) not in stdout  # the written back of sheet 2 was kept


@pytest.mark.parametrize("policy", ["always", "never"])
def test_nothing_is_reported_dropped_when_the_policy_decides(tmp_path, out, capsys, policy) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet(0)])
    assert process(out, pages, "--backs", policy) == 0
    assert "backs dropped" not in capsys.readouterr().out


def test_enhancements_that_changed_nothing_are_counted(tmp_path, out, capsys, monkeypatch) -> None:
    monkeypatch.setattr("fastfoto_linux.cli.options.restore_colour", lambda img, dpi: img)
    pages = write_sheets(tmp_path / "raw", [plain_sheet()])
    assert main(["process", *map(str, pages), "--out", str(out), "--no-orient"]) == 0
    assert names(out) == ["FastFoto_0001.jpg"]
    assert "enhanced: 0 (1 unchanged)" in capsys.readouterr().out


def test_a_degraded_sheet_is_exit_1_keeps_the_original_and_is_named(
    tmp_path, out, capsys, monkeypatch
) -> None:
    def boom(img, dpi):
        raise ValueError("restore exploded")

    monkeypatch.setattr("fastfoto_linux.cli.options.restore_colour", boom)
    pages = write_sheets(tmp_path / "raw", [plain_sheet()])
    assert main(["process", *map(str, pages), "--out", str(out), "--no-orient"]) == 1
    assert names(out) == ["FastFoto_0001.jpg"]
    err = capsys.readouterr().err
    assert "sheet 1" in err
    assert "enhancer" in err
    assert "restore exploded" in err
    assert "Traceback" not in err


def test_an_incomplete_last_sheet_is_listed_in_the_summary(tmp_path, out, capsys) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet(0), plain_sheet(1)])[:3]
    assert process(out, pages) == 0
    stdout = capsys.readouterr().out
    assert "incomplete sheet" in stdout
    assert page_name(3) in stdout
    assert "told apart" not in stdout
