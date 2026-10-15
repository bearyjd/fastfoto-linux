"""``ffscan library check`` and ``fix`` through ``main``: summaries, exit codes, safety."""

import csv
from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.library.apply import MANIFEST_NAME
from fastfoto_linux.library.plan import PLAN_COLUMNS
from tests.face_images import load_astronaut, textured_photo_without_faces
from tests.library.jpeg_helpers import (
    displayed_array,
    make_jpeg,
    same_picture,
    sideways_jpeg,
    stored_array,
    tree_snapshot,
    write_file,
)

TURNED_90 = "2001/trip_0001_a.jpg"  # shows the portrait turned 90 clockwise, no tag
TURNED_270 = "2001/trip_0002_a.jpg"  # shows it turned 270 clockwise, via tag 6
UPRIGHT = "2001/trip_0003_a.jpg"
PLAIN_BACK = "2001/trip_0003_b.jpg"
FRONT_LIKE_BACK = "2001/trip_0004_b.jpg"
FACELESS = "2002/blank_0005_a.jpg"
JUNK = "bad.jpg"
NOTES = "notes.txt"


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    root = tmp_path / "lib"
    write_file(root, TURNED_90, sideways_jpeg(90, None))
    write_file(root, TURNED_270, sideways_jpeg(270, 6))
    write_file(root, UPRIGHT, sideways_jpeg(0, 1))
    write_file(root, PLAIN_BACK, make_jpeg(textured_photo_without_faces(300, 400)))
    write_file(root, FRONT_LIKE_BACK, sideways_jpeg(180, None))
    write_file(root, FACELESS, make_jpeg(textured_photo_without_faces(300, 400)))
    write_file(root, JUNK, b"not an image")
    write_file(root, NOTES, b"hello")
    return root


@pytest.fixture
def work(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


def check(lib: Path, work: Path, *extra: str) -> int:
    return main(["library", "check", str(lib), "--plan", str(work / "plan.csv"), *extra])


def fix(work: Path, lib: Path, dest: Path, *extra: str) -> int:
    plan = work / "plan.csv"
    return main(["library", "fix", str(plan), "--source", str(lib), "--out", str(dest), *extra])


def plan_rows(work: Path) -> dict[str, dict[str, str]]:
    with (work / "plan.csv").open(encoding="utf-8", newline="") as handle:
        return {row["path"]: row for row in csv.DictReader(handle)}


def one_line_error(capsys: pytest.CaptureFixture[str]) -> str:
    err = capsys.readouterr().err
    assert "Traceback" not in err
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 1, err
    return lines[0]


# --- check ----------------------------------------------------------------------------


def test_check_prints_the_counts(lib: Path, work: Path, capsys) -> None:
    assert check(lib, work) == 0
    out = capsys.readouterr().out
    assert "files seen: 8 (JPEG: 7, other formats ignored: 1)" in out
    assert "to rotate: 2 (90: 1, 180: 0, 270: 1)" in out
    assert "already upright: 1" in out
    assert "undecided: 1" in out
    assert "skipped: 3 (back: 1, back-looks-like-front: 1, unreadable: 1)" in out
    assert "backs that look like fronts: 1" in out


def test_check_writes_the_plan_and_nothing_else(lib: Path, work: Path) -> None:
    before = tree_snapshot(lib)
    assert check(lib, work) == 0
    assert tree_snapshot(lib) == before
    assert [p.name for p in work.iterdir()] == ["plan.csv"]
    rows = plan_rows(work)
    assert set(rows) == {
        TURNED_90,
        TURNED_270,
        UPRIGHT,
        PLAIN_BACK,
        FRONT_LIKE_BACK,
        FACELESS,
        JUNK,
    }
    assert (rows[TURNED_90]["action"], rows[TURNED_90]["rotate_cw"]) == ("rotate", "270")
    assert (rows[TURNED_270]["action"], rows[TURNED_270]["rotate_cw"]) == ("rotate", "90")
    assert rows[UPRIGHT]["action"] == "keep"
    text = (work / "plan.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(PLAN_COLUMNS)
    assert str(lib) not in text


def test_check_gives_the_same_plan_with_worker_processes(lib: Path, work: Path, tmp_path) -> None:
    assert check(lib, work) == 0
    other = tmp_path / "other"
    other.mkdir()
    assert check(lib, other, "--jobs", "2") == 0
    assert (other / "plan.csv").read_bytes() == (work / "plan.csv").read_bytes()


def test_checking_again_replaces_the_old_plan(lib: Path, work: Path) -> None:
    assert check(lib, work) == 0
    assert check(lib, work) == 0


# --- fix ------------------------------------------------------------------------------


def test_fix_writes_upright_copies_and_a_manifest(lib: Path, work: Path, tmp_path, capsys) -> None:
    dest = tmp_path / "fixed"
    assert check(lib, work) == 0
    capsys.readouterr()
    assert fix(work, lib, dest, "--mkdir") == 0
    assert "written: 2" in capsys.readouterr().out
    written = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert written == {TURNED_90, TURNED_270, MANIFEST_NAME}
    for name in (TURNED_90, TURNED_270):
        data = (dest / name).read_bytes()
        assert same_picture(displayed_array(data), load_astronaut())
        assert stored_array(data).tobytes() == stored_array((lib / name).read_bytes()).tobytes()
    manifest = (dest / MANIFEST_NAME).read_text(encoding="utf-8").splitlines()
    assert manifest[0] == "path,old_tag,new_tag"
    assert sorted(manifest[1:]) == [f"{TURNED_90},1,8", f"{TURNED_270},6,3"]


def test_a_second_check_of_the_fixed_copies_proposes_nothing(
    lib: Path, work: Path, tmp_path, capsys
) -> None:
    dest = tmp_path / "fixed"
    assert check(lib, work) == 0
    assert fix(work, lib, dest, "--mkdir") == 0
    capsys.readouterr()
    again = tmp_path / "again"
    again.mkdir()
    assert main(["library", "check", str(dest), "--plan", str(again / "plan.csv")]) == 0
    out = capsys.readouterr().out
    assert "to rotate: 0 (90: 0, 180: 0, 270: 0)" in out
    assert "already upright: 2" in out


def test_the_library_is_untouched_by_a_whole_run(lib: Path, work: Path, tmp_path) -> None:
    before = tree_snapshot(lib)
    assert check(lib, work) == 0
    assert fix(work, lib, tmp_path / "fixed", "--mkdir") == 0
    assert tree_snapshot(lib) == before


def test_a_stale_row_is_reported_and_the_rest_is_written(
    lib: Path, work: Path, tmp_path, capsys
) -> None:
    dest = tmp_path / "fixed"
    assert check(lib, work) == 0
    write_file(lib, TURNED_90, sideways_jpeg(90, None, date=True))  # edited after the check
    capsys.readouterr()
    assert fix(work, lib, dest, "--mkdir") == 1
    captured = capsys.readouterr()
    assert "written: 1" in captured.out
    assert "stale: 1" in captured.out
    assert TURNED_90 in captured.err
    assert "Traceback" not in captured.err
    assert (dest / TURNED_270).exists() and not (dest / TURNED_90).exists()


def test_existing_destination_files_are_reported_and_kept(
    lib: Path, work: Path, tmp_path, capsys
) -> None:
    dest = tmp_path / "fixed"
    assert check(lib, work) == 0
    assert fix(work, lib, dest, "--mkdir") == 0
    capsys.readouterr()
    assert fix(work, lib, dest) == 1
    out = capsys.readouterr().out
    assert "written: 0" in out
    assert "already there: 2" in out


# --- usage errors ---------------------------------------------------------------------


def test_check_needs_an_existing_folder(tmp_path: Path, work: Path, capsys) -> None:
    assert check(tmp_path / "nope", work) == 2
    assert "not a folder" in one_line_error(capsys)
    assert list(work.iterdir()) == []


def test_check_refuses_a_plan_inside_the_library(lib: Path, capsys) -> None:
    before = tree_snapshot(lib)
    assert main(["library", "check", str(lib), "--plan", str(lib / "plan.csv")]) == 2
    assert "inside" in one_line_error(capsys)
    assert tree_snapshot(lib) == before


def test_check_does_not_overwrite_a_file_that_is_not_a_plan(lib: Path, work: Path, capsys) -> None:
    (work / "plan.csv").write_text("my notes\n", encoding="utf-8")
    assert check(lib, work) == 2
    assert "not a plan" in one_line_error(capsys)
    assert (work / "plan.csv").read_text(encoding="utf-8") == "my notes\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["library"],
        ["library", "check"],
        ["library", "check", "somewhere"],
        ["library", "fix", "plan.csv"],
        ["library", "check", "somewhere", "--plan", "p.csv", "--jobs", "0"],
        ["library", "check", "somewhere", "--plan", "p.csv", "--jobs", "many"],
    ],
)
def test_bad_command_lines_exit_2(argv: list[str]) -> None:
    assert main(argv) == 2


def test_fix_refuses_a_destination_inside_the_library(lib: Path, work: Path, capsys) -> None:
    assert check(lib, work) == 0
    before = tree_snapshot(lib)
    assert fix(work, lib, lib / "fixed", "--mkdir") == 2
    assert "overlap" in one_line_error(capsys)
    assert tree_snapshot(lib) == before


def test_fix_refuses_a_library_inside_the_destination(
    lib: Path, work: Path, tmp_path: Path, capsys
) -> None:
    assert check(lib, work) == 0
    before = tree_snapshot(lib)
    assert fix(work, lib, tmp_path) == 2
    assert "overlap" in one_line_error(capsys)
    assert tree_snapshot(lib) == before


def test_fix_needs_the_destination_to_exist_unless_told_otherwise(
    lib: Path, work: Path, tmp_path: Path, capsys
) -> None:
    assert check(lib, work) == 0
    dest = tmp_path / "later"
    assert fix(work, lib, dest) == 2
    assert "--mkdir" in one_line_error(capsys)
    assert not dest.exists()
    assert fix(work, lib, dest, "--mkdir") == 0
    assert dest.is_dir()


def test_a_bad_plan_is_refused_before_anything_is_written(
    lib: Path, work: Path, tmp_path: Path, capsys
) -> None:
    assert check(lib, work) == 0
    text = (work / "plan.csv").read_text(encoding="utf-8")
    (work / "plan.csv").write_text(text.replace(",rotate,", ",explode,", 1), encoding="utf-8")
    dest = tmp_path / "fixed"
    dest.mkdir()
    assert fix(work, lib, dest) == 2
    assert "unknown action" in one_line_error(capsys)
    assert list(dest.iterdir()) == []


def test_a_plan_row_that_escapes_the_library_is_refused(
    lib: Path, work: Path, tmp_path: Path, capsys
) -> None:
    assert check(lib, work) == 0
    text = (work / "plan.csv").read_text(encoding="utf-8")
    (work / "plan.csv").write_text(text.replace(TURNED_90, "../outside.jpg"), encoding="utf-8")
    dest = tmp_path / "fixed"
    dest.mkdir()
    assert fix(work, lib, dest) == 2
    assert "line 2" in one_line_error(capsys)
    assert list(dest.iterdir()) == []


def test_a_missing_plan_or_library_is_a_usage_error(
    lib: Path, work: Path, tmp_path: Path, capsys
) -> None:
    dest = tmp_path / "fixed"
    dest.mkdir()
    assert fix(work, lib, dest) == 2  # no plan.csv yet
    assert "plan" in one_line_error(capsys)
    assert check(lib, work) == 0
    assert fix(work, tmp_path / "gone", dest) == 2
    assert "not a folder" in one_line_error(capsys)
