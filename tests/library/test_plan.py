"""The plan file: round trip, and every field checked on the way in."""

import csv
import io
from pathlib import Path

import pytest

from fastfoto_linux.library.plan import (
    PLAN_COLUMNS,
    Action,
    PlanError,
    PlanRow,
    read_plan,
    write_plan,
)

SHA = "a" * 64
ROTATE = {
    "path": "2001/holiday_0001_a.jpg",
    "action": "rotate",
    "rotate_cw": "90",
    "old_tag": "1",
    "new_tag": "6",
    "score": "0.375",
    "reason": "faces-upright-after-turn",
    "size": "1234",
    "mtime_ns": "1700000000123456789",
    "sha256": SHA,
}
KEEP = {**ROTATE, "path": "b.jpg", "action": "keep", "rotate_cw": "0", "new_tag": "", "sha256": ""}


def rows() -> tuple[PlanRow, ...]:
    return (
        PlanRow("a.jpg", Action.ROTATE, 270, 6, 1, 0.875, "turn", 10, 5, SHA),
        PlanRow("dir/b.jpg", Action.KEEP, 0, 1, None, 0.0, "undecided", 11, 6, ""),
        PlanRow("c.jpg", Action.SKIP, 0, None, None, 0.0, "unreadable", 12, 7, ""),
        PlanRow("d.jpg", Action.SKIP, 0, 5, None, 0.0, "mirrored-tag", 13, 8, ""),
    )


def csv_text(*records: dict[str, str], header: tuple[str, ...] = PLAN_COLUMNS) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for record in records:
        writer.writerow([record.get(column, "") for column in header])
    return out.getvalue()


@pytest.fixture
def src(tmp_path: Path) -> Path:
    path = tmp_path / "lib"
    path.mkdir()
    return path


def read_text(tmp_path: Path, src: Path, text: str) -> tuple[PlanRow, ...]:
    plan = tmp_path / "plan.csv"
    plan.write_text(text, encoding="utf-8")
    return read_plan(plan, src)


# --- writing and round trip -----------------------------------------------------------


def test_rows_survive_a_round_trip(tmp_path: Path, src: Path) -> None:
    plan = tmp_path / "plan.csv"
    write_plan(plan, rows())
    assert read_plan(plan, src) == rows()


def test_the_file_has_the_documented_columns_and_three_decimals(tmp_path: Path) -> None:
    plan = tmp_path / "plan.csv"
    write_plan(plan, rows())
    lines = plan.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(PLAN_COLUMNS)
    assert lines[1].split(",")[5] == "0.875"
    assert len(lines) == 1 + len(rows())


def test_scores_are_written_with_three_decimals(tmp_path: Path) -> None:
    plan = tmp_path / "plan.csv"
    write_plan(plan, (PlanRow("a.jpg", Action.KEEP, 0, 1, None, 0.123456, "upright", 1, 2, ""),))
    assert plan.read_text(encoding="utf-8").splitlines()[1].split(",")[5] == "0.123"


def test_no_absolute_path_reaches_the_plan(tmp_path: Path) -> None:
    plan = tmp_path / "plan.csv"
    write_plan(plan, rows())
    assert str(tmp_path) not in plan.read_text(encoding="utf-8")


def test_odd_but_legal_file_names_round_trip(tmp_path: Path, src: Path) -> None:
    odd = PlanRow('we, "ird"\nname.jpg', Action.KEEP, 0, 1, None, 0.0, "upright", 1, 2, "")
    plan = tmp_path / "plan.csv"
    write_plan(plan, (odd,))
    assert read_plan(plan, src) == (odd,)


def test_a_header_only_plan_is_empty(tmp_path: Path, src: Path) -> None:
    assert read_text(tmp_path, src, csv_text()) == ()


def test_review_is_a_valid_action_and_keeps_its_fields(tmp_path: Path, src: Path) -> None:
    (row,) = read_text(tmp_path, src, csv_text({**KEEP, "action": "review"}))
    assert row.action is Action.REVIEW


# --- validation -----------------------------------------------------------------------


def bad_cases() -> dict[str, dict[str, str]]:
    return {
        "parent traversal": {"path": "../x.jpg"},
        "deep traversal": {"path": "a/../../x.jpg"},
        "absolute path": {"path": "/etc/passwd"},
        "empty path": {"path": ""},
        "unknown action": {"action": "explode"},
        "empty action": {"action": ""},
        "angle not a number": {"rotate_cw": "ninety"},
        "angle not a quarter turn": {"rotate_cw": "45"},
        "angle out of range": {"rotate_cw": "360"},
        "negative angle": {"rotate_cw": "-90"},
        "zero angle on a rotate row": {"rotate_cw": "0", "new_tag": "1"},
        "old tag out of range": {"old_tag": "9"},
        "old tag zero": {"old_tag": "0"},
        "old tag text": {"old_tag": "x"},
        "new tag mirrored": {"new_tag": "2"},
        "new tag missing on rotate": {"new_tag": ""},
        "new tag disagrees with the turn": {"new_tag": "3"},
        "score not a number": {"score": "high"},
        "score not finite": {"score": "nan"},
        "negative score": {"score": "-0.5"},
        "size negative": {"size": "-1"},
        "size text": {"size": "big"},
        "mtime text": {"mtime_ns": "yesterday"},
        "mtime negative": {"mtime_ns": "-5"},
        "sha too short": {"sha256": "abc"},
        "sha not hex": {"sha256": "z" * 64},
        "sha missing on rotate": {"sha256": ""},
    }


@pytest.mark.parametrize("name", sorted(bad_cases()))
def test_a_bad_field_is_refused_with_its_line_number(tmp_path: Path, src: Path, name: str) -> None:
    text = csv_text(KEEP, {**ROTATE, **bad_cases()[name]})
    with pytest.raises(PlanError, match=r"line 3\b"):
        read_text(tmp_path, src, text)


def test_a_symlink_leaving_the_library_is_refused(tmp_path: Path, src: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (src / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PlanError, match=r"line 2\b"):
        read_text(tmp_path, src, csv_text({**ROTATE, "path": "escape/x.jpg"}))


def test_a_duplicate_path_is_refused(tmp_path: Path, src: Path) -> None:
    with pytest.raises(PlanError, match=r"line 3\b.*twice|line 3\b.*duplicate"):
        read_text(tmp_path, src, csv_text(ROTATE, ROTATE))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "path,action\nx.jpg,keep\n",
        csv_text(header=(*PLAN_COLUMNS, "extra")),
        ",".join(reversed(PLAN_COLUMNS)) + "\n",
    ],
    ids=["empty file", "missing columns", "extra column", "reordered header"],
)
def test_a_wrong_header_is_refused(tmp_path: Path, src: Path, text: str) -> None:
    with pytest.raises(PlanError, match=r"header|columns|empty"):
        read_text(tmp_path, src, text)


def test_a_short_row_is_refused(tmp_path: Path, src: Path) -> None:
    text = ",".join(PLAN_COLUMNS) + "\nx.jpg,keep,0\n"
    with pytest.raises(PlanError, match=r"line 2\b"):
        read_text(tmp_path, src, text)


def test_a_missing_plan_file_is_a_plan_error(tmp_path: Path, src: Path) -> None:
    with pytest.raises(PlanError, match="cannot read"):
        read_plan(tmp_path / "nope.csv", src)


def test_nothing_is_returned_when_any_row_is_bad(tmp_path: Path, src: Path) -> None:
    text = csv_text(KEEP, {**KEEP, "path": "c.jpg", "action": "nope"})
    with pytest.raises(PlanError):
        read_text(tmp_path, src, text)
