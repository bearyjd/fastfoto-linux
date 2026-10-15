"""Re-orienting the user's real, private fronts. Counts and booleans only - never image data."""

import contextlib
import csv
import io
import shutil
from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.library.jpeg_exif import set_orientation
from tests.conftest import REAL_SCANS_DIR
from tests.library.jpeg_helpers import CLOCKWISE_BY_TAG, stored_array

pytestmark = pytest.mark.real_scans

EXPECTED_PAGES = 8
TURN_TAGS = (6, 3, 8)  # cycled over the fronts: 90, 180 and 270 degrees clockwise


def run(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return main(argv)


def plan_rows(plan: Path) -> dict[str, dict[str, str]]:
    with plan.open(encoding="utf-8", newline="") as handle:
        return {row["path"]: row for row in csv.DictReader(handle)}


@pytest.fixture(scope="module")
def album(tmp_path_factory) -> Path:
    pages = sorted(REAL_SCANS_DIR.glob("photo-*.png"))
    assert len(pages) == EXPECTED_PAGES, f"expected {EXPECTED_PAGES} pages, found {len(pages)}"
    out = tmp_path_factory.mktemp("album")
    assert run(["process", *map(str, pages), "--out", str(out), "--date", "1975-06"]) == 0
    return out


@pytest.fixture(scope="module")
def fronts(album: Path) -> list[Path]:
    found = sorted(p for p in album.rglob("*.jpg") if not p.stem.endswith("_b"))
    assert found, "no fronts were produced"
    return found


@pytest.fixture(scope="module")
def checked(album: Path, tmp_path_factory) -> dict[str, dict[str, str]]:
    """The plan for the freshly processed (upright, untagged) album."""
    work = tmp_path_factory.mktemp("baseline")
    assert run(["library", "check", str(album), "--plan", str(work / "plan.csv")]) == 0
    return plan_rows(work / "plan.csv")


@pytest.fixture(scope="module")
def turned(album: Path, fronts: list[Path], tmp_path_factory) -> tuple[Path, dict[str, int]]:
    """A copy of the album whose fronts are tagged sideways by known angles."""
    library = tmp_path_factory.mktemp("library")
    angles: dict[str, int] = {}
    for index, front in enumerate(fronts):
        relative = front.relative_to(album)
        tag = TURN_TAGS[index % len(TURN_TAGS)]
        target = library / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(set_orientation(front.read_bytes(), tag))
        angles[relative.as_posix()] = CLOCKWISE_BY_TAG[tag]
    for other in sorted(album.rglob("*.jpg")):
        if not (library / other.relative_to(album)).exists():
            shutil.copy2(other, library / other.relative_to(album))
    return library, angles


def test_some_fronts_have_faces_to_go_by(checked: dict[str, dict[str, str]]) -> None:
    confident = [row for row in checked.values() if row["reason"] == "upright"]
    assert len(confident) >= 1, f"{len(confident)} of {len(checked)} files were decided"


def test_upright_fronts_are_kept_and_backs_never_rotate(checked: dict[str, dict[str, str]]) -> None:
    assert all(row["action"] != "rotate" for row in checked.values())
    backs = [row for name, row in checked.items() if Path(name).stem.endswith("_b")]
    assert all(row["action"] == "skip" for row in backs)


def test_the_plan_proposes_the_restoring_turn_for_every_front_with_faces(
    turned: tuple[Path, dict[str, int]], checked: dict[str, dict[str, str]], tmp_path: Path
) -> None:
    library, angles = turned
    assert run(["library", "check", str(library), "--plan", str(tmp_path / "plan.csv")]) == 0
    rows = plan_rows(tmp_path / "plan.csv")
    decided = [name for name in angles if checked[name]["reason"] == "upright"]
    assert decided, "no front had a clear orientation to restore"
    wrong = [
        name
        for name in decided
        if rows[name]["action"] != "rotate"
        or int(rows[name]["rotate_cw"]) != (360 - angles[name]) % 360
        or rows[name]["new_tag"] != "1"
    ]
    assert not wrong, f"{len(wrong)} of {len(decided)} fronts got the wrong turn"
    undecided = [name for name in angles if name not in decided]
    assert all(rows[name]["action"] == "keep" for name in undecided)


def test_fixing_restores_the_fronts_without_touching_pixels(
    turned: tuple[Path, dict[str, int]], tmp_path: Path
) -> None:
    library, _ = turned
    plan, dest = tmp_path / "plan.csv", tmp_path / "fixed"
    assert run(["library", "check", str(library), "--plan", str(plan)]) == 0
    assert (
        run(["library", "fix", str(plan), "--source", str(library), "--out", str(dest), "--mkdir"])
        == 0
    )
    fixed = [p for p in dest.rglob("*.jpg")]
    assert fixed, "nothing was written"
    for path in fixed:
        original = library / path.relative_to(dest)
        assert (
            stored_array(path.read_bytes()).tobytes()
            == stored_array(original.read_bytes()).tobytes()
        )
    again = tmp_path / "again.csv"
    assert run(["library", "check", str(dest), "--plan", str(again)]) == 0
    assert all(row["action"] != "rotate" for row in plan_rows(again).values())
